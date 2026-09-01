# Preliminary GitHub upload

Create an empty repository on GitHub, for example `eovsa-flare-selfcal`, with
no generated README or license. Then run these commands from this project:

```bash
cd "/path/to/eovsa-selfcal-modern"

git init
git branch -M main
git add .gitignore README.md setup_macos.sh scripts docs \
  config/2024-05-14-x8.8.example.json \
  config/2024-05-14-x8.8-smoke-test.example.json

# Add the gallery only after the group confirms that these derived PNGs may be public.
git add examples/2024-05-14-x8.8

git status --short
git diff --cached --stat
git commit -m "Add modern EOVSA flare self-calibration workflow"
git remote add origin git@github.com:mal-wickline/eovsa-flare-selfcal.git
git push -u origin main
```

Before committing, `git status` must not contain an IDB directory, `*.ms`,
`*.G`, `*.fits`, `*.npz`, `runs/`, `preflight/`, `.venv/`, CASA logs, `.netrc`,
or a JSON file containing a personal absolute path. The `.gitignore` blocks the
large generated products, but this manual check remains required.

The smallest preliminary first commit can omit `examples/` until public-release
approval; all source and documentation remain usable without those PNGs.
