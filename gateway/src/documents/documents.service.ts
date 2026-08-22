import {
  BadGatewayException,
  ForbiddenException,
  Injectable,
  NotFoundException,
} from '@nestjs/common';
import { AiClient, MoteurIaIndisponibleError } from '../ai/ai.client';
import { AuditService } from '../audit/audit.service';
import { CatalogService } from '../catalog/catalog.service';
import {
  ACTIONS_AUDIT,
  ActionAcces,
  DocumentCatalogue,
  NiveauSens,
  UtilisateurJwt,
} from '../common/types';
import { ConnectorFactory } from '../connectors/connector.factory';
import {
  RessourceIntrouvableError,
  SourceIndisponibleError,
} from '../connectors/connector.interface';
import { LockedException } from '../common/locked.exception';
import { NiveauInconnuError, PolicyService } from '../policy/policy.service';

export interface Restitution {
  contenu: Buffer;
  typeMime: string;
  politiqueAppliquee: ActionAcces;
  niveauMax: NiveauSens;
  documentId: string;
  auditId: string;
  nomFichier: string;
}

export interface ContexteAppel {
  utilisateur: UtilisateurJwt;
  adresseIp: string | null;
  format: 'original' | 'texte';
}

/**
 * Point d'application de la politique (PEP au sens du NIST SP 800-207).
 *
 * Séquence de `GET /documents/:id/contenu`, dans cet ordre exact :
 *   1. JWT validé en amont par le garde global (sinon 401, journalisé) ;
 *   2. chargement du document          -> absent : 404, journalisé ;
 *   3. statut != 'analyse'             -> 423,      journalisé ;
 *   4. décision du PDP ;
 *   5. `refus`                         -> 403,      journalisé ;
 *   6. lecture des octets via le connecteur de la source ;
 *   7. `masque` / `pseudonymise`       -> appel du moteur IA ;
 *   8. écriture au journal — **avant** de rendre la réponse ;
 *   9. réponse avec les en-têtes de politique.
 *
 * L'étape 8 précède l'écriture de la réponse : journaliser après aurait pour
 * effet qu'une coupure réseau produise un accès non tracé (piège n°4).
 */
@Injectable()
export class DocumentsService {

  constructor(
    private readonly catalogue: CatalogService,
    private readonly politique: PolicyService,
    private readonly audit: AuditService,
    private readonly connecteurs: ConnectorFactory,
    private readonly ia: AiClient,
  ) {}

  async restituer(documentId: string, contexte: ContexteAppel): Promise<Restitution> {
    const { utilisateur, adresseIp } = contexte;

    // --- 2. Chargement du document -----------------------------------------
    const document = await this.catalogue.document(documentId);
    if (!document) {
      await this.audit.append({
        utilisateurId: utilisateur.sub,
        roleEffectif: utilisateur.role,
        documentId: null,
        action: ACTIONS_AUDIT.REFUS,
        politiqueAppliquee: 'refus',
        adresseIp,
        details: { motif: 'document_inconnu', documentDemande: documentId },
      });
      throw new NotFoundException('Document inconnu du catalogue');
    }

    // --- 3 & 4. Décision ----------------------------------------------------
    let action: ActionAcces;
    try {
      action = this.decider(document, utilisateur.role);
    } catch (erreur) {
      if (erreur instanceof NiveauInconnuError) {
        await this.audit.append({
          utilisateurId: utilisateur.sub,
          roleEffectif: utilisateur.role,
          documentId: document.id,
          action: ACTIONS_AUDIT.REFUS,
          politiqueAppliquee: 'refus',
          adresseIp,
          details: { motif: 'document_non_analyse', statut: document.statut },
        });
        throw new LockedException(
          `Document au statut « ${document.statut} » : analyse non terminée, ` +
            'la lecture est refusée pour le moment.',
        );
      }
      throw erreur;
    }

    const niveauMax = document.niveauMax as NiveauSens;

    // --- 5. Refus -----------------------------------------------------------
    if (action === 'refus') {
      await this.audit.append({
        utilisateurId: utilisateur.sub,
        roleEffectif: utilisateur.role,
        documentId: document.id,
        action: ACTIONS_AUDIT.REFUS,
        politiqueAppliquee: 'refus',
        niveauEnCause: niveauMax,
        adresseIp,
        details: { motif: 'politique_refus' },
      });
      throw new ForbiddenException(
        `Accès refusé : le rôle « ${utilisateur.role} » ne peut pas lire un document ` +
          `de niveau « ${niveauMax} »`,
      );
    }

    // --- 6. Lecture des octets ---------------------------------------------
    const contenuOriginal = await this.lireOctets(document, utilisateur, adresseIp);

    // --- 7. Protection ------------------------------------------------------
    let contenu = contenuOriginal;
    let typeMime = document.typeMime ?? 'application/octet-stream';
    let nbProtegees = 0;

    if (action === 'masque' || action === 'pseudonymise') {
      const protege = await this.proteger(document, contenuOriginal, action, niveauMax);
      contenu = protege.contenu;
      typeMime = protege.typeMimeSortie || typeMime;
      nbProtegees = protege.nbEntitesProtegees;
    }

    if (contexte.format === 'texte' && action === 'complet') {
      // Le format texte n'est proposé qu'en restitution intégrale : produire
      // du texte à partir d'un document protégé demanderait une seconde
      // extraction, avec le risque de divergence que cela implique.
      typeMime = 'text/plain; charset=utf-8';
    }

    // --- 8. Journalisation AVANT la réponse ---------------------------------
    const auditId = await this.audit.append({
      utilisateurId: utilisateur.sub,
      roleEffectif: utilisateur.role,
      documentId: document.id,
      action: ACTIONS_AUDIT.LECTURE,
      politiqueAppliquee: action,
      niveauEnCause: niveauMax,
      adresseIp,
      details: {
        cheminSource: document.cheminSource,
        octets: contenu.length,
        nbEntitesProtegees: nbProtegees,
        format: contexte.format,
      },
    });

    // --- 9. Réponse ---------------------------------------------------------
    return {
      contenu,
      typeMime,
      politiqueAppliquee: action,
      niveauMax,
      documentId: document.id,
      auditId,
      nomFichier: document.cheminSource.split('/').pop() ?? document.id,
    };
  }

  /**
   * Étapes 3 et 4 isolées : le cœur testable de la décision.
   *
   * Le rôle est un paramètre, jamais un champ d'instance : le service est un
   * singleton, un état partagé entre requêtes ferait décider une requête avec
   * le rôle d'une autre.
   */
  private decider(document: DocumentCatalogue, role: string): ActionAcces {
    if (document.statut !== 'analyse' || document.niveauMax === null) {
      throw new NiveauInconnuError();
    }
    return this.politique.decide(role, document.niveauMax);
  }

  async metadonnees(
    documentId: string,
    contexte: Pick<ContexteAppel, 'utilisateur' | 'adresseIp'>,
  ): Promise<{
    id: string;
    source: string;
    cheminSource: string;
    typeMime: string | null;
    statut: string;
    niveauMax: NiveauSens | null;
    tailleOctets: number | null;
    dateDecouverte: Date;
    dateAnalyse: Date | null;
    entites: Array<{ typeEntite: string; niveau: NiveauSens; page: number | null }>;
  }> {
    const document = await this.catalogue.document(documentId);
    if (!document) {
      throw new NotFoundException('Document inconnu du catalogue');
    }

    const source = await this.catalogue.source(document.sourceId);
    const entites = await this.catalogue.entitesDe(document.id);

    // Consulter les métadonnées reste un accès : il est journalisé, même s'il
    // ne révèle aucune valeur.
    await this.audit.append({
      utilisateurId: contexte.utilisateur.sub,
      roleEffectif: contexte.utilisateur.role,
      documentId: document.id,
      action: ACTIONS_AUDIT.LECTURE,
      niveauEnCause: document.niveauMax,
      adresseIp: contexte.adresseIp,
      details: { portee: 'metadonnees' },
    });

    return {
      id: document.id,
      source: source?.libelle ?? document.sourceId,
      cheminSource: document.cheminSource,
      typeMime: document.typeMime,
      statut: document.statut,
      niveauMax: document.niveauMax,
      tailleOctets: document.tailleOctets,
      dateDecouverte: document.dateDecouverte,
      dateAnalyse: document.dateAnalyse,
      entites,
    };
  }

  private async lireOctets(
    document: DocumentCatalogue,
    utilisateur: UtilisateurJwt,
    adresseIp: string | null,
  ): Promise<Buffer> {
    const source = await this.catalogue.source(document.sourceId);
    if (!source) {
      throw new BadGatewayException('Source du document introuvable');
    }

    try {
      return await this.connecteurs.pour(source).lire(document.cheminSource);
    } catch (erreur) {
      await this.audit.append({
        utilisateurId: utilisateur.sub,
        roleEffectif: utilisateur.role,
        documentId: document.id,
        action: ACTIONS_AUDIT.REFUS,
        politiqueAppliquee: 'refus',
        niveauEnCause: document.niveauMax,
        adresseIp,
        details: { motif: 'source_indisponible', erreur: String(erreur) },
      });

      if (erreur instanceof RessourceIntrouvableError) {
        throw new NotFoundException(
          'Le document est au catalogue mais absent de la source de stockage',
        );
      }
      if (erreur instanceof SourceIndisponibleError) {
        throw new BadGatewayException(erreur.message);
      }
      throw new BadGatewayException(String(erreur));
    }
  }

  private async proteger(
    document: DocumentCatalogue,
    contenu: Buffer,
    action: 'masque' | 'pseudonymise',
    niveauMax: NiveauSens,
  ): Promise<{ contenu: Buffer; typeMimeSortie: string; nbEntitesProtegees: number }> {
    try {
      const reponse = await this.ia.proteger({
        documentId: document.id,
        typeMime: document.typeMime,
        contenu,
        action,
        // Le seuil est le niveau à partir duquel le rôle n'a plus le droit de
        // voir en clair. Il vaut le niveau maximal du document : tout ce qui
        // atteint ce niveau est protégé, le reste demeure lisible.
        niveauSeuil: niveauMax,
        nomFichier: document.cheminSource,
      });

      // Réversibilité de la pseudonymisation : la valeur arrive déjà chiffrée
      // par le moteur, la base ne voit jamais de clair.
      for (const lien of reponse.correspondances) {
        if (lien.valeurChiffreeBase64) {
          await this.catalogue.enregistrerPseudonyme({
            empreinte: lien.empreinte,
            jeton: lien.jeton,
            valeurChiffreeBase64: lien.valeurChiffreeBase64,
          });
        }
      }

      return reponse;
    } catch (erreur) {
      if (erreur instanceof MoteurIaIndisponibleError) {
        // Refus par défaut : sans protection applicable, on ne rend rien.
        throw new BadGatewayException(
          'Le moteur de protection est indisponible : la restitution est refusée',
        );
      }
      throw erreur;
    }
  }
}
