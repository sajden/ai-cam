#!/bin/bash
# Lägger till cp210x boot-kommando i /etc/wsl.conf
if grep -q "\[boot\]" /etc/wsl.conf 2>/dev/null; then
  echo "[boot] finns redan i /etc/wsl.conf — kontrollera manuellt"
else
  printf '\n[boot]\ncommand = /sbin/modprobe cp210x\n' >> /etc/wsl.conf
  echo "Klart! Starta om WSL2 med: wsl --shutdown (i PowerShell)"
fi
cat /etc/wsl.conf
