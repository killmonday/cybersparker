#!/bin/sh
chown -R vscode:vscode /workspaces
chmod +x run_claude.sh
# su vscode && chmod +x run_claude.sh  && mkdir ~/.claude-code-router/   && bash

su - vscode -c 'mkdir ~/.claude-code-router/'
su vscode
