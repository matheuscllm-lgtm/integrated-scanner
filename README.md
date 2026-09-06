# integrated-scanner

Busca coordenada de cartas Pokémon no MyP Cards e CardTrader, com adaptadores
COMC/Liga, API HTTP e entrega no formato MyP Cards.

```powershell
python -m pip install -r requirements.txt
python run_integrated.py --profile group2 --sources myp,ct
```

Cada fonte precisa do seu repositório, dependências e credenciais. Veja
[CLAUDE.md](CLAUDE.md) para instalação, fontes, testes, limites e API.

- Coleta nova por execução; falhas nunca reutilizam preços antigos.
- TCGCSV padrão no CardTrader; estado e cache de preços isolados por execução.
- Referências clicáveis, carta com número, dois links e todas as linhas em baldes.
- Comparação conservadora por set, número, variante, condição e idioma.
- Status explícito de sucesso, parcial e falha; releitura histórica separada.
- Margem bruta, sem taxas; o scanner não decide compras.

[DELIVERY_CHAT.md](DELIVERY_CHAT.md) rege a entrega: resultados no chat,
nunca publicados no GitHub. CI e testes usam somente dados sintéticos.
