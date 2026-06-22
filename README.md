# integrated-scanner

Scanner **integrado** de singles Pokémon: orquestra os 4 scanners existentes
(MYP, CardTrader, COMC, Liga) como subprocessos caixa-preta, unifica os
resultados num schema único e entrega **uma tabela markdown completa no chat**
— com flag ⭐ para Pokémon notórios e score heurístico de valorização (0-100).

📖 **Documentação completa e acessível: [CLAUDE.md](CLAUDE.md)** (o que é,
como rodar, armadilhas de threshold, status honesto de cada fonte).

## TL;DR

```powershell
cd C:\Users\mathe\integrated-scanner
.venv\Scripts\python.exe run_integrated.py --profile quick   # principais sets SV
.venv\Scripts\python.exe run_integrated.py --skip-scan       # só re-normaliza outputs existentes
```

## Setup (uma vez)

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install pandas openpyxl pytest
.venv\Scripts\python.exe -m pytest tests/ -q   # 86 testes
```

Pré-requisito: os 4 repos das fontes clonados nos caminhos canônicos com os
venvs deles criados (ver CLAUDE.md, seção "Repos das fontes").

## Invariantes (regras canônicas do operador)

- Margem = SÓ margem bruta `(revenda − compra) / compra`, corte 30%, zero taxas.
- NM-only (cada scanner já garante). Piso R$50 / $10 (idem).
- Entrega = tabela markdown completa (todos os deals); xlsx local é só apoio.
- O integrado ranqueia e flagea, mas **nunca decide compra** — operador decide capital.
