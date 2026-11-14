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
# O dump não traz os arquivos do media_volume: os documentos da biblioteca e as
# fotos dos recibos do reembolso, que são comprovante. Eles vão cifrados, um a
# um, para a pasta media/ do destino, na mesma árvore de pastas do volume. Para
# restaurar, copie a pasta media/ da rede, e na cópia:
#   find media -name '*.gpg' -exec sh -c 'gpg --decrypt "$1" > "${1%.gpg}" && rm "$1"' _ {} \;
#   docker compose -f deploy/docker-compose.yml cp media/. django:/app/media_root/
#   docker compose -f deploy/docker-compose.yml exec -u root django chown -R django:django /app/media_root
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
# O nome do projeto do compose (name: intranet) e o do volume
MEDIA_VOLUME="intranet_media_volume"

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

# Os arquivos do media_volume. O nome de cada um é sorteado e ele nunca é
# regravado, então só vão os que ainda não estão na rede: a execução de hora em
# hora leva só o que chegou na última hora. Nada é apagado de lá, nem quando o
# arquivo sai do portal: recibo é comprovante.
MEDIA="$(docker volume inspect --format '{{ .Mountpoint }}' "$MEDIA_VOLUME")"

(cd "$MEDIA" && find . -type f -print0) | while IFS= read -r -d '' file; do
    file="${file#./}"
    target="$DESTINATION/media/$file.gpg"
    [ -f "$target" ] && continue
    mkdir -p "$(dirname "$target")"
    # Cifra com outro nome e só então dá o definitivo: a cópia interrompida no
    # meio não passa por arquivo já guardado, e é refeita na próxima execução.
    gpg --batch --yes --trust-model always --encrypt \
        --recipient "$RECIPIENT" --output "$target.tmp" "$MEDIA/$file"
    mv -- "$target.tmp" "$target"
done
