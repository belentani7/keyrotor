"""Find deploy-related repos and the three named projects in repos.json."""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

repos = json.load(open(r"C:\Users\USER\belentani-unified\repos.json", encoding="utf-8"))

targets = ["manos", "abiertas", "lingua", "aberta", "lenguaforge",
           "lengua-forge", "ux-academy", "uxacademy", "academy", "academia"]
deploy_kw = ["vercel", "netlify", "cloudflare", "cf-pages", "cf-workers",
             "wrangler", "deploy", "hosting", "supabase", "live-site", "live"]

print("=== A) PROYECTOS NOMBRADOS (manos/lingua/lenguaforge/academy) ===")
for r in repos:
    name = (r.get("name") or "").lower()
    desc = (r.get("description") or "").lower()
    if any(t in name for t in targets) or any(t in desc for t in targets):
        print(f"{r['name']} | vis={r.get('visibility')} | arch={r.get('isArchived')} | push={str(r.get('pushedAt'))[:10]} | {str(r.get('description'))[:80]}")

print()
print("=== B) REPOS CON PALABRAS DE DEPLOY ===")
for r in repos:
    name = (r.get("name") or "").lower()
    desc = (r.get("description") or "").lower()
    if any(k in name for k in deploy_kw) or any(k in desc for k in deploy_kw):
        print(f"{r['name']} | vis={r.get('visibility')} | arch={r.get('isArchived')} | push={str(r.get('pushedAt'))[:10]} | {str(r.get('description'))[:60]}")
