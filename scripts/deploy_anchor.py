#!/usr/bin/env python3
"""Deploy EvidenceAnchor.sol to Base Sepolia (or mainnet).

Compiles the contract using solcx and deploys via web3.py.

Environment variables:
    VR_ANCHOR_PRIVATE_KEY: Deployer private key (hex, with or without 0x)
    VR_BASE_RPC_URL: JSON-RPC URL (default: https://sepolia.base.org)

Usage:
    pip install web3 py-solc-x
    python scripts/deploy_anchor.py

After deployment, set VR_ANCHOR_CONTRACT=<address> in your environment.
"""

import os
import sys
import json

try:
    from web3 import Web3
except ImportError:
    sys.exit("web3 not installed. Run: pip install web3")

try:
    import solcx
except ImportError:
    sys.exit("py-solc-x not installed. Run: pip install py-solc-x")


CONTRACT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "contracts", "EvidenceAnchor.sol"
)


def main() -> None:
    private_key = os.environ.get("VR_ANCHOR_PRIVATE_KEY", "")
    if not private_key:
        sys.exit("Set VR_ANCHOR_PRIVATE_KEY env var (deployer private key)")

    rpc_url = os.environ.get("VR_BASE_RPC_URL", "https://sepolia.base.org")
    print(f"Deploying to: {rpc_url}")

    # Read and compile the contract
    with open(CONTRACT_PATH) as f:
        source = f.read()

    solcx.install_solc("0.8.20")
    compiled = solcx.compile_source(
        source,
        output_values=["abi", "bin"],
        solc_version="0.8.20",
    )

    # The key is "<source_path>:EvidenceAnchor" or just ":EvidenceAnchor"
    contract_key = None
    for k in compiled:
        if "EvidenceAnchor" in k:
            contract_key = k
            break

    if contract_key is None:
        sys.exit("EvidenceAnchor not found in compiled output")

    abi = compiled[contract_key]["abi"]
    bytecode = compiled[contract_key]["bin"]

    # Deploy
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        sys.exit(f"Cannot connect to {rpc_url}")

    account = w3.eth.account.from_key(private_key)
    print(f"Deployer: {account.address}")
    print(f"Balance: {w3.from_wei(w3.eth.get_balance(account.address), 'ether')} ETH")

    Contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx = Contract.constructor().build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 500_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": w3.eth.chain_id,
    })

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"Tx sent: {tx_hash.hex()}")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt.status != 1:
        sys.exit("Deployment transaction failed")

    contract_address = receipt.contractAddress
    print(f"\n✓ EvidenceAnchor deployed at: {contract_address}")
    print(f"  Chain ID: {w3.eth.chain_id}")
    print(f"  Tx hash:  {tx_hash.hex()}")
    print(f"\nSet this in your environment:")
    print(f"  VR_ANCHOR_CONTRACT={contract_address}")

    # Save deployment artifact
    artifact = {
        "address": contract_address,
        "chain_id": w3.eth.chain_id,
        "rpc_url": rpc_url,
        "tx_hash": tx_hash.hex(),
        "deployer": account.address,
        "abi": abi,
    }
    artifact_path = os.path.join(
        os.path.dirname(__file__), "..", "contracts", "deployment.json"
    )
    with open(artifact_path, "w") as f:
        json.dump(artifact, f, indent=2)
    print(f"  Artifact saved to: {artifact_path}")


if __name__ == "__main__":
    main()
