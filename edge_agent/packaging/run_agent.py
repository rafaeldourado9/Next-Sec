"""Entry point pro build PyInstaller — `agent.main.main` não é um script,
é uma função de módulo, e o PyInstaller precisa de um arquivo executável
como ponto de análise."""
from agent.main import main

if __name__ == "__main__":
    main()
