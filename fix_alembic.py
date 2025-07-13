import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()
db_url = os.getenv('DATABASE_URL')

# Parse the URL
import urllib.parse as urlparse
url = urlparse.urlparse(db_url)

try:
    conn = psycopg2.connect(
        host=url.hostname,
        port=url.port,
        database=url.path[1:],
        user=url.username,
        password=url.password
    )

    cur = conn.cursor()

    # Check all alembic versions
    cur.execute('SELECT version_num FROM alembic_version;')
    all_versions = cur.fetchall()
    print(f'All alembic versions: {[v[0] for v in all_versions]}')

    # Clear all entries and set the correct one
    cur.execute('DELETE FROM alembic_version;')
    cur.execute('INSERT INTO alembic_version (version_num) VALUES (%s);', ('jkl345mno678',))
    conn.commit()

    # Verify update
    cur.execute('SELECT version_num FROM alembic_version;')
    new_version = cur.fetchone()
    print(f'Updated alembic version: {new_version[0]}')

    cur.close()
    conn.close()
    print('Successfully updated alembic version!')

except Exception as e:
    print(f'Error: {e}')