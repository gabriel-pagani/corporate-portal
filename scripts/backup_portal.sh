#!/bin/bash
# Gera o backup do banco, cifra com GPG e o envia para a pasta de rede, apagando
# de lá o que passar de sete dias.
#
# O dump traz os hashes de senha e todos os dados do portal, e a pasta de rede é
# lida por mais gente do que o servidor. Por isso só a versão cifrada sai daqui.
# A cifra usa só a chave pública, que fica no keyring do root. A chave privada
# fica fora do servidor, com quem restaura:
#   gpg --decrypt portal-....sql.gpg > portal-....sql
#   make restore-database file=portal-....sql
#
# Roda no servidor pelo cron do root, de hora em hora. O cron chama
# /usr/local/sbin/backup-portal.sh, que é um link para este arquivo: assim o que
# roda é sempre a versão do repositório, e o projeto é achado pelo caminho do
# próprio script. Com o caminho escrito à mão, o backup parou em silêncio quando
# a pasta do projeto mudou de nome.
#
# Instalação, na pasta do projeto:
#   ln -sf "$PWD/scripts/backup_portal.sh" /usr/local/sbin/backup-portal.sh
#
# Chave pública, uma vez, como root:
#   gpg --import chave-publica-backup.asc
#
# Linha do crontab do root, com o e-mail ou o ID da chave em GPG_RECIPIENT:
#   0 * * * * GPG_RECIPIENT=<chave> /usr/bin/flock -n /run/lock/backup-portal.lock /usr/local/sbin/backup-portal.sh >> /var/log/backup-portal.log 2>&1
set -euo pipefail

PROJECT="$(dirname "$(dirname "$(readlink -f "$0")")")"
MOUNT="/mnt/serverfile-users"
DESTINATION="$MOUNT/Tecnologia/backups-portal"
RECIPIENT="${GPG_RECIPIENT:?ERRO: defina GPG_RECIPIENT com a chave pública do backup}"

if ! gpg --list-keys "$RECIPIENT" >/dev/null 2>&1; then
    echo "ERRO: chave pública de $RECIPIENT não encontrada no keyring" >&2
    exit 1
fi

# Aciona a montagem automática e verifica o destino.
if ! stat "$DESTINATION" >/dev/null 2>&1; then
    echo "ERRO: pasta de backup da rede não está acessível" >&2
    exit 1
fi

if ! findmnt -rn -T "$DESTINATION" -o FSTYPE | grep -qx cifs; then
    echo "ERRO: destino não está em um compartilhamento CIFS" >&2
    exit 1
fi

cd "$PROJECT"
make backup-database

# O dump em texto só é apagado depois que a versão cifrada fica pronta. Também
# entra aqui o que sobrou de uma execução que falhou antes de cifrar.
for file in backups/portal-*.sql; do
    [ -f "$file" ] || continue
    gpg --batch --yes --trust-model always --encrypt \
        --recipient "$RECIPIENT" --output "$file.gpg" "$file"
    rm -f -- "$file"
done

# Remove o arquivo local somente após uma transferência bem-sucedida.
for file in backups/portal-*.sql.gpg; do
    [ -f "$file" ] || continue
    rsync --archive --remove-source-files -- "$file" "$DESTINATION/"
done

# Mantém somente os backups dos últimos sete dias na rede. O padrão também
# pega os .sql em texto de antes da cifra, que somem quando vencem.
find "$DESTINATION" -maxdepth 1 -type f \
    -name 'portal-*.sql*' -mmin +10080 -delete
