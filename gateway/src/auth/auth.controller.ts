import { Body, Controller, Ip, Post } from '@nestjs/common';
import { IsNotEmpty, IsString } from 'class-validator';
import { AuthService, Jetons } from './auth.service';
import { Public } from './decorators';

export class DemandeJetonDto {
  @IsString()
  @IsNotEmpty()
  utilisateur!: string;

  @IsString()
  @IsNotEmpty()
  motDePasse!: string;
}

export class DemandeRafraichissementDto {
  @IsString()
  @IsNotEmpty()
  refreshToken!: string;
}

@Controller('api/v1/auth')
export class AuthController {
  constructor(private readonly auth: AuthService) {}

  @Public()
  @Post('token')
  async token(@Body() corps: DemandeJetonDto, @Ip() ip: string): Promise<Jetons> {
    return this.auth.authentifier(corps.utilisateur, corps.motDePasse, ip ?? null);
  }

  @Public()
  @Post('rafraichir')
  async rafraichir(@Body() corps: DemandeRafraichissementDto): Promise<Jetons> {
    return this.auth.rafraichir(corps.refreshToken);
  }
}
