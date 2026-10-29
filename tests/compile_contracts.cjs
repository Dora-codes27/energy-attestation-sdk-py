// Compile Suno's EnergyRegistry/Resolver (0.8.28) and EAS core (0.8.27) with solc-js, same settings as their hardhat.config.ts
const fs = require('fs'), path = require('path');
const root = process.argv[2], out = process.argv[3];
const req = (m) => require(path.join(root, 'node_modules', m));
function findImports(p) {
  for (const base of [root, path.join(root, 'node_modules')]) {
    const f = path.join(base, p);
    if (fs.existsSync(f)) return { contents: fs.readFileSync(f, 'utf8') };
  }
  return { error: 'not found: ' + p };
}
function build(solc, sources) {
  const input = { language: 'Solidity', sources: Object.fromEntries(sources.map(s => [s, { content: fs.readFileSync(path.join(root, s.startsWith('contracts/') ? '' : 'node_modules', s), 'utf8') }])),
    settings: { optimizer: { enabled: true, runs: 200 }, evmVersion: 'cancun', viaIR: true, outputSelection: { '*': { '*': ['abi', 'evm.bytecode.object'] } } } };
  const o = JSON.parse(solc.compile(JSON.stringify(input), { import: findImports }));
  const errs = (o.errors || []).filter(e => e.severity === 'error');
  if (errs.length) { console.error(errs.map(e => e.formattedMessage).join('\n')); process.exit(1); }
  return o.contracts;
}
const res = {};
const c28 = build(req('solc'), ['contracts/EnergyRegistry.sol', 'contracts/EnergyAttestationResolver.sol', '@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol']);
const c27 = build(req('solc27'), ['@ethereum-attestation-service/eas-contracts/contracts/EAS.sol', '@ethereum-attestation-service/eas-contracts/contracts/SchemaRegistry.sol']);
for (const [file, name] of [['contracts/EnergyRegistry.sol','EnergyRegistry'],['contracts/EnergyAttestationResolver.sol','EnergyAttestationResolver'],['@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol','ERC1967Proxy']]) res[name] = c28[file][name];
for (const [file, name] of [['@ethereum-attestation-service/eas-contracts/contracts/EAS.sol','EAS'],['@ethereum-attestation-service/eas-contracts/contracts/SchemaRegistry.sol','SchemaRegistry']]) res[name] = c27[file][name];
for (const [n, c] of Object.entries(res)) res[n] = { abi: c.abi, bytecode: '0x' + c.evm.bytecode.object };
fs.writeFileSync(out, JSON.stringify(res));
console.log('compiled', Object.keys(res).map(n => `${n}(${(res[n].bytecode.length-2)/2}B)`).join(', '));
