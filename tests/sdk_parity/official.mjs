import { readFileSync } from 'node:fs';
import { cloud } from '@spectrum-ts/core';
import { imessage } from '@spectrum-ts/imessage';

let tokenRequest;
globalThis.fetch = async (url, options) => {
  tokenRequest = {
    url: String(url),
    method: options.method,
    authorization: options.headers.get('authorization'),
  };
  return new Response(JSON.stringify({
    succeed: true,
    data: { type: 'shared', token: 'test-token', expiresIn: 100 },
  }), { status: 200, headers: { 'content-type': 'application/json' } });
};

const token = await cloud.issueImessageTokens('project', 'secret');
const provider = imessage.config();
const space = await provider.__definition.space.create({
  input: { users: [{ id: '+15551234567' }] },
  client: [{ phone: 'shared' }],
});
const proto = readFileSync(
  new URL('../proto/photon/imessage/v1/message_service.proto', import.meta.resolve('@photon-ai/advanced-imessage/grpc')),
  'utf8',
);
const request = proto.match(/message SendTextMessageRequest \{([\s\S]*?)^\}/m)?.[1];
const fields = request && Object.fromEntries(
  [...request.matchAll(/^\s*(?:optional )?string (\w+) = (\d+);/gm)].map(([, name, number]) => [name, Number(number)]),
);
const packageName = proto.match(/^package ([\w.]+);/m)?.[1];
if (!request || !packageName || !proto.includes('rpc SendTextMessage(SendTextMessageRequest) returns (MessageResponse)')) {
  throw new Error('Photon message contract changed');
}
console.log(JSON.stringify({ tokenRequest, token, chatGuid: space.id, fields,
  method: `/${packageName}.MessageService/SendTextMessage` }));
