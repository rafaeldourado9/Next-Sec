"""Entry point pro build PyInstaller — `agent.cli.main` não é um script,
é uma função de módulo, e o PyInstaller precisa de um arquivo executável
como ponto de análise.

Passou a apontar pra `agent.cli` (e não mais direto pra `agent.main.main`) na
ADR-018: o mesmo executável precisa atender tanto o serviço Windows (sem
argumentos → roda o agente, comportamento inalterado) quanto o instalador
(`activate`/`status`/`fingerprint`)."""
import sys

from agent.cli import main

if __name__ == "__main__":
    sys.exit(main())
