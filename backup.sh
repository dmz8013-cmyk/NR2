#!/bin/bash
# NR2 Database Backup Script

# Configuration
BACKUP_DIR="backups"
DATE=$(date +%Y%m%d_%H%M%S)
DB_FILE="app.db"
BACKUP_FILE="${BACKUP_DIR}/nr2_backup_${DATE}.db"

# Create backup directory if it doesn't exist
mkdir -p ${BACKUP_DIR}

# Backup database
if [ -f ${DB_FILE} ]; then
    echo "Backing up database..."
    cp ${DB_FILE} ${BACKUP_FILE}
    echo "Backup created: ${BACKUP_FILE}"

    # Compress backup
    gzip ${BACKUP_FILE}
    echo "Backup compressed: ${BACKUP_FILE}.gz"

    # Keep only last 30 backups
    ls -t ${BACKUP_DIR}/nr2_backup_*.gz | tail -n +31 | xargs -r rm
    echo "Old backups cleaned up"

    echo "Backup completed successfully!"
else
    echo "Error: Database file not found: ${DB_FILE}"
    exit 1
fi

# Backup uploads (optional)
UPLOADS_DIR="app/static/uploads"
UPLOADS_BACKUP="${BACKUP_DIR}/uploads_backup_${DATE}.tar.gz"

if [ -d ${UPLOADS_DIR} ]; then
    echo "Backing up uploads..."
    tar -czf ${UPLOADS_BACKUP} ${UPLOADS_DIR}
    echo "Uploads backup created: ${UPLOADS_BACKUP}"

    # Keep only last 7 uploads backups
    ls -t ${BACKUP_DIR}/uploads_backup_*.tar.gz | tail -n +8 | xargs -r rm
    echo "Old uploads backups cleaned up"
fi

echo "All backups completed!"
