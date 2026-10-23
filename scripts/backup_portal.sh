#!/bin/bash
# Gera o backup do banco e o envia para a pasta de rede, apagando de lá o que
# passar de sete dias.
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
# Linha do crontab do root:
#   0 * * * * /usr/bin/flock -n /run/lock/backup-portal.lock /usr/local/sbin/backup-portal.sh >> /var/log/backup-portal.log 2>&1
set -euo pipefail

PROJECT="$(dirname "$(dirname "$(readlink -f "$0")")")"
MOUNT="/mnt/serverfile-users"
DESTINATION="$MOUNT/Tecnologia/backups-portal"

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

# Remove o arquivo local somente após uma transferência bem-sucedida.
for file in backups/portal-*.sql; do
    [ -f "$file" ] || continue
    rsync --archive --remove-source-files -- "$file" "$DESTINATION/"
done

# Mantém somente os backups dos últimos sete dias na rede.
find "$DESTINATION" -maxdepth 1 -type f \
    -name 'portal-*.sql' -mmin +10080 -delete
