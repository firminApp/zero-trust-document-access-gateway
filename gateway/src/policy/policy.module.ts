import { Module } from '@nestjs/common';
import { PolicyRepository } from './policy.repository';
import { PolicyService } from './policy.service';

@Module({
  providers: [PolicyRepository, PolicyService],
  exports: [PolicyService],
})
export class PolicyModule {}
