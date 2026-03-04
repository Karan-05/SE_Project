''' This file contains methods to connect to Mysql database '''
import argparse
import logging
from datetime import datetime, timedelta
from typing import List, Set

import mysql.connector
import xlsxwriter
from mysql.connector import errorcode
from progress.bar import Bar

from migrations import MigrationRunner
from schema_registry import TableRegistry

logger = logging.getLogger(__name__)


class dbConnect:
    def __init__(self, args) -> None:
        self.db_username = args['username']
        self.db_hostname = args['hostname']
        self.db_password = args['password']
        self.db_port = int(args['port']) if isinstance(args['port'], str) else args['port']
        self.db_name = args['database']
        self.db_connection = None
        overrides = {
            "TOPCODER_DB_TABLE_CHALLENGES": args.get("challenges_table") or args.get("table_name"),
            "TOPCODER_DB_TABLE_MAPPING": args.get("challenge_member_mapping_table"),
            "TOPCODER_DB_TABLE_MEMBERS": args.get("members_table"),
        }
        self.table_registry = TableRegistry({k: v for k, v in overrides.items() if v})

        # Connects to the Mysql server
        self.connect_db_server()
        # Connects to the given database
        self.check_database(self.db_name)
        # Ensure schema is up to date
        self._apply_migrations()

    def connect_db_server(self):
        ''' Makes the connection with the MySql database usin the provided config '''
        try:
            logger.info("Making connection to the Mysql server")
            mydb = mysql.connector.connect(
                user=self.db_username,
                host=self.db_hostname,
                password=self.db_password,
                port=self.db_port
            )
            self.db_connection = mydb
            logger.info("Mysql server connected successfully")

        except mysql.connector.Error as err:
            if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
                logger.error("Access denied: verify user name or password")
            elif err.errno == errorcode.ER_BAD_DB_ERROR:
                logger.error("Database does not exist")
            else:
                logger.exception("Unhandled database connection error")
            raise RuntimeError("Failed to connect to MySQL; check credentials and server status.") from err

    def check_database(self, database_name: str):
        ''' Checks if database exists otherwise creates it '''
        if self.db_connection is None:
            raise RuntimeError("Database connection not established.")
        db_obj = self.db_connection.cursor()
        db_obj.execute(f'CREATE DATABASE IF NOT EXISTS {database_name}')

        db_obj.execute(f'USE {self.db_name}')
        logger.info('Database %s ready for use', self.db_name)

    def _apply_migrations(self):
        runner = MigrationRunner(
            self.db_connection,
            self.table_registry,
            logger=logger,
        )
        runner.apply()

    def check_member(
        self,
        member_set: Set[str],
        *,
        max_age_hours: int | None = None,
        force_refresh: bool = False,
    ) -> Set[str]:
        """Remove handles that already exist (and are fresh) from the provided set."""
        if force_refresh or not member_set:
            return member_set

        members_table = self.table_registry.get("members")
        placeholders = ",".join(["%s"] * len(member_set))
        sql = f"SELECT memberHandle, updatedAt FROM {members_table.name} WHERE memberHandle IN ({placeholders})"
        db_obj = self.db_connection.cursor()
        try:
            db_obj.execute(sql, tuple(member_set))
            rows = db_obj.fetchall()
        except mysql.connector.Error:
            logger.exception("Failed while checking member handles")
            return member_set

        cutoff: datetime | None = None
        if max_age_hours is not None:
            cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)

        member_check = Bar("Check Members Exists", max=len(rows))
        for handle, updated_at in rows:
            if handle not in member_set:
                member_check.next()
                continue
            if cutoff is None:
                member_set.remove(handle)
            else:
                if isinstance(updated_at, datetime) and updated_at >= cutoff:
                    member_set.remove(handle)
            member_check.next()
        member_check.finish()
        return member_set

    def upload_data(self, challenge_data, table_key: str) -> bool:
        ''' Uploads the given data to the appropriate Database table '''
        db_obj = self.db_connection.cursor()
        try:
            table = self.table_registry.get(table_key)
        except KeyError:
            table = next(
                (
                    schema
                    for schema in self.table_registry.all().values()
                    if schema.name.lower() == table_key.lower()
                ),
                None,
            )
            if table is None:
                raise KeyError(f"Unknown table '{table_key}'") from None
        try:
            values = [challenge_data.get(column) for column in table.insert_columns]
            placeholders = ",".join(["%s" for _ in values])
            sql_query = f'INSERT INTO {table.name} ({table.insert_clause}) VALUES ({placeholders})'
            if table.upsert_columns:
                update_clause = ", ".join(
                    [f"{column}=VALUES({column})" for column in table.upsert_columns]
                )
                sql_query = f"{sql_query} ON DUPLICATE KEY UPDATE {update_clause}"
            db_obj.execute(sql_query, values)
            self.db_connection.commit()
            return db_obj.lastrowid
        except mysql.connector.Error as err:
            if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
                logger.error("Access denied during insert into %s", table.name)
            elif err.errno == errorcode.ER_BAD_DB_ERROR:
                logger.error("Database does not exist while inserting into %s", table.name)
            elif err.errno == 1406:
                logger.error("Data too long for column when inserting into %s: %s", table.name, err)
            else:
                logger.exception("Unhandled error inserting into %s", table.name)
            return -1

    def excel_uploader(self, table_key: str) -> None:
        ''' Uploads sql data to excel sheet '''
        db_obj = self.db_connection.cursor()
        try:
            table = self.table_registry.get(table_key)
        except KeyError:
            table = next(
                (
                    schema
                    for schema in self.table_registry.all().values()
                    if schema.name.lower() == table_key.lower()
                ),
                None,
            )
            if table is None:
                raise KeyError(f"Unknown table '{table_key}'") from None
        col_names: List[str] = list(table.select_columns)

        workbook = xlsxwriter.Workbook(f'{table.name}.xlsx')
        worksheet = workbook.add_worksheet()
        format3 = workbook.add_format({'num_format': 'mm/dd/yy'})

        # Add column names
        row: int = 0
        col: int = 0
        for col_name in col_names:
            worksheet.write(row, col, col_name)
            col += 1
        row += 1
        try:
            sql_query = f'SELECT {table.select_clause} FROM {table.name};'
            db_obj.execute(sql_query)

            date_columns = {
                "registrationStartDate",
                "registrationEndDate",
                "submissionStartDate",
                "submissionEndDate",
                "startDate",
                "endDate",
            }
            for record in db_obj:
                for idx, value in enumerate(record):
                    column_name = col_names[idx]
                    if table.key == "challenges" and column_name in date_columns and value is not None:
                        worksheet.write(row, idx, value, format3)
                    else:
                        worksheet.write(row, idx, value)
                row += 1

        except mysql.connector.Error as err:
            logger.exception('Failed exporting table %s to Excel', table.name)

        workbook.close()


def main(args):
    db_config = {
        "username": args.username,
        "hostname": args.hostname,
        "password": args.password,
        "port": args.port,
        "database": args.database,
        "table_name": args.table_name,
        "challenges_table": args.challenges_table,
        "members_table": args.members_table,
        "challenge_member_mapping_table": args.challenge_member_mapping_table,
    }
    db = dbConnect(db_config)
    db.excel_uploader(args.export_table)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog='dbConnector',
                                     usage='%(prog)s [options] path',
                                     description='connects the Mysql databse to upload the data',
                                     epilog="Made by Mahir Dhall"
                                     )

    parser.add_argument('-ho', '--hostname', type=str, metavar='hostname',
                        default='localhost',
                        help="Optional hostname, default set as localhost")

    parser.add_argument('-po', '--port', type=str, metavar="port",
                        default='3306', help="optional port number, default set as 3306")

    parser.add_argument('-u', '--username', type=str, default="root",
                        help="optional username, default set as root")

    parser.add_argument('-pa', '--password', default='password', type=str, metavar='password',
                        help="optional password, default set as an empty string '' ")

    parser.add_argument('-db', '--database', metavar='database_name', type=str,
                        help='optional Database name, default set as dataCollector',
                        default='dataCollector')

    parser.add_argument('-t', '--table_name', default='Challenges',
                        help='optional (legacy) Challenges table name override')
    parser.add_argument('--challenges-table', dest='challenges_table', default=None,
                        help='override the name of the challenges table')
    parser.add_argument('--members-table', dest='members_table', default=None,
                        help='override the name of the members table')
    parser.add_argument('--mapping-table', dest='challenge_member_mapping_table', default=None,
                        help='override the name of the challenge-member mapping table')
    parser.add_argument('--export-table', dest='export_table', default='challenge_member_mapping',
                        choices=['challenges', 'challenge_member_mapping', 'members'],
                        help='which table to export to Excel (default: challenge_member_mapping)')

    args = parser.parse_args()

    main(args)
