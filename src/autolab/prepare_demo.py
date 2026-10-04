"""Create fresh isolated charter-only final-demo state; no network or approvals."""
import json
from autolab.final_demo import create_demo

def main():
    receipt = create_demo()
    print(json.dumps(receipt, indent=2))
    print('Fresh isolated project created. No scientific results or approvals were copied.')

if __name__ == '__main__':
    main()
