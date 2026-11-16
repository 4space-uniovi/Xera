# Instalación

> Pendiente: el instalador (`scripts/install.sh`) llega en la Fase 5.

## Desarrollo (Fase 1)

```bash
sudo apt install python3-venv python3-pip     # una sola vez, si falta
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
./scripts/dev.sh
```
