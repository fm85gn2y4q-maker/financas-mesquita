@echo off
REM Disparado pelo Agendador de Tarefas do Windows, aos domingos.
REM O registro de cada execucao fica em publicacao.log, ao lado deste arquivo.
REM
REM Usa o Python do venv do projeto, nao o global: o global e compartilhado e
REM fragil, e uma tarefa agendada que depende dele quebra quando outro projeto
REM mexe nas dependencias.
cd /d "%~dp0"
".venv\Scripts\python.exe" publicar_automatico.py >> publicacao_saida.log 2>&1
