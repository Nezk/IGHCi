import os
import sys
import json
from jupyter_client.kernelspec import KernelSpecManager

def install_kernel_spec():
    
    kernel_json = {
        "argv": [sys.executable, "-m", "IGHCi", "-f", "{connection_file}"],
        "display_name": "IGHCi",
        "language": "haskell"
    }
    
    kernel_dir = os.path.join(
        KernelSpecManager().kernel_dirs[0],
        "ighci"
    )
    
    os.makedirs(kernel_dir, exist_ok = True)
    with open(os.path.join(kernel_dir, "kernel.json"), "w") as f:
        json.dump(kernel_json, f, indent = 2)

def main():
    install_kernel_spec()
    print("IGHCi kernel installed successfully")
