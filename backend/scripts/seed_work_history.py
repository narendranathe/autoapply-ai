# ruff: noqa: E501
"""
Seed Narendranath's work history into the backend.

Usage:
  # Production (Fly.io):
  python scripts/seed_work_history.py --user-id <your-clerk-user-id> --api https://autoapply-ai-api.fly.dev/api/v1

  # Local dev:
  python scripts/seed_work_history.py --dev
  (uses ENVIRONMENT=development fallback — picks first DB user automatically)
"""

import argparse
import json
import sys
import urllib.request

ENTRIES = [
    {
        "entry_type": "work",
        "company_name": "ExponentHR",
        "role_title": "Data Engineer",
        "start_date": "July 2024",
        "end_date": None,
        "is_current": True,
        "location": "Dallas, TX",
        "sort_order": 0,
        "bullets": [
            "Led enterprise data platform modernization across ETL reliability, deployment automation, and analytics delivery for multi-tenant HR/payroll systems",
            "Built CI/CD pipelines via Azure DevOps, compressing deployment cycles from 3 months to 14 days (85% faster)",
            "Designed CDC-based SSIS ETL pipelines with 70% faster runtime and 30% infrastructure cost reduction",
            "Optimized SQL Server OLAP star schema with index tuning, reducing analytical query latency by 20%",
            "Automated cross-functional reporting workflows using Git and Azure DevOps data, eliminating 15+ manual hours per sprint",
            "Implemented Always-On Availability Groups achieving <1 hr recovery time and 99.9% uptime",
        ],
        "technologies": [
            "Azure DevOps",
            "SSIS",
            "SQL Server",
            "Python",
            "CI/CD",
            "OLAP",
            "CDC",
            "ETL",
            "Contained AAG",
        ],
        "team_size": None,
    },
    {
        "entry_type": "work",
        "company_name": "Missouri University of Science and Technology",
        "role_title": "Data Engineer",
        "start_date": "August 2023",
        "end_date": "July 2024",
        "is_current": False,
        "location": "Rolla, MO",
        "sort_order": 1,
        "bullets": [
            "Engineered Azure AI Anomaly Detector pipelines achieving 95%+ detection accuracy and 40% reduction in false positives",
            "Built REST APIs with configurable sensitivity thresholds for real-time anomaly detection streams",
            "Deployed scalable microservices on AKS with auto-scaling, achieving 99.9% availability and 50% infrastructure cost reduction",
        ],
        "technologies": [
            "Azure AI",
            "AKS",
            "Kubernetes",
            "REST API",
            "Python",
            "Docker",
            "Azure",
        ],
        "team_size": None,
    },
    {
        "entry_type": "work",
        "company_name": "Zomato",
        "role_title": "Business Analyst",
        "start_date": "March 2018",
        "end_date": "September 2020",
        "is_current": False,
        "location": "India",
        "sort_order": 2,
        "bullets": [
            "Built real-time eCommerce analytics and competitor intelligence platform contributing to 9% market share gain",
            "Implemented Elasticsearch search engine (100K+ documents) improving search-to-conversion metrics",
            "Automated customer query resolution reducing support desk workload by 80%",
            "Drove 200% revenue increase via agile campaign optimization and A/B testing on marketing strategies",
        ],
        "technologies": [
            "Elasticsearch",
            "Python",
            "SQL",
            "A/B Testing",
            "Analytics",
        ],
        "team_size": None,
    },
    {
        "entry_type": "work",
        "company_name": "Udaan",
        "role_title": "Business Analyst",
        "start_date": "2020",
        "end_date": "2021",
        "is_current": False,
        "location": "India",
        "sort_order": 3,
        "bullets": [
            "Built demand forecasting and inventory optimization models generating $4M annual savings (7% ROI increase)",
            "Achieved 99.3% fulfillment rate via JIT inventory and warehouse model optimization",
            "Managed cross-functional supply chain team of 10+ across planning and operations",
        ],
        "technologies": ["Python", "SQL", "Forecasting", "Supply Chain Analytics"],
        "team_size": 10,
    },
    {
        "entry_type": "work",
        "company_name": "C2FO",
        "role_title": "Product Intern",
        "start_date": "Summer 2022",
        "end_date": "Summer 2022",
        "is_current": False,
        "location": "Kansas City, KS",
        "sort_order": 4,
        "bullets": [
            "Authored PRD for preferred offers tool, halving development time through clear requirements definition",
            "Performed SQL analysis on user behavior across B2B transaction platform to surface conversion insights",
        ],
        "technologies": ["SQL", "Product Management", "B2B Analytics"],
        "team_size": None,
    },
    {
        "entry_type": "education",
        "company_name": "Missouri University of Science and Technology",
        "role_title": "M.S. Information Science and Technology",
        "start_date": "January 2022",
        "end_date": "December 2023",
        "is_current": False,
        "location": "Rolla, MO",
        "sort_order": 5,
        "bullets": [
            "GPA: 4.0 / 4.0",
            "Data Science minor certification",
            "Published research: Sentiment Analysis for Visitor Insights (co-authored, DOI published)",
            "Coursework: IoT systems, computer architecture, project management, machine learning",
        ],
        "technologies": [
            "Python",
            "NLP",
            "VADER",
            "RoBERTa",
            "spaCy",
            "scikit-learn",
            "DBSCAN",
            "K-Means",
            "PyTorch",
        ],
        "team_size": None,
    },
]


def seed(api_base: str, headers: dict) -> None:
    url = f"{api_base}/work-history/seed"
    body = json.dumps(ENTRIES).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            print(f"Seeded: {result['created']} created, {result['skipped']} skipped")
    except urllib.error.HTTPError as e:
        print(f"Error {e.code}: {e.read().decode()}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="https://autoapply-ai-api.fly.dev/api/v1")
    parser.add_argument("--user-id", help="Clerk user ID (from extension options page)")
    parser.add_argument(
        "--dev", action="store_true", help="Use development fallback (no user ID needed)"
    )
    args = parser.parse_args()

    if args.dev:
        # ENVIRONMENT=development uses the first DB user automatically
        headers: dict = {}
    elif args.user_id:
        headers = {"X-Clerk-User-Id": args.user_id}
    else:
        parser.error("Provide --user-id or --dev")

    seed(args.api, headers)


if __name__ == "__main__":
    main()
