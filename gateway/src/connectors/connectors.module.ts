import { Module } from '@nestjs/common';
import { ConnectorFactory } from './connector.factory';

@Module({
  providers: [ConnectorFactory],
  exports: [ConnectorFactory],
})
export class ConnectorsModule {}
