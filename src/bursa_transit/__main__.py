import json
from .publishing import publication_decision

def main() -> None:
    print(json.dumps({
        "project": "Bursa Open Transit",
        "milestone": "M0.1",
        "mode": "development-only",
        "real_data_ingestion": False,
        "publication_allowed": publication_decision().allowed,
    }, indent=2))

if __name__ == "__main__":
    main()
