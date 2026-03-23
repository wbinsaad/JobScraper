import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import psycopg2
from scrapy import signals

from SeekSpider.core.config import config
from SeekSpider.core.database import DatabaseManager
from SeekSpider.core.output_manager import OutputManager


class JsonExportPipeline:
    """Pipeline to export scraped items to JSON files and logs"""

    def open_spider(self, spider):
        # Get region from spider
        region = getattr(spider, 'region', 'Perth')

        # Use OutputManager for directory structure
        self.output_manager = OutputManager('seek_spider', region=region)
        self.output_dir = self.output_manager.setup()

        # Initialize data file
        self.jobs_file = open(self.output_manager.get_file_path('jobs.jsonl'), 'w', encoding='utf-8')
        self.items_count = 0

        # Setup log file in the same directory
        self.log_file_path = self.output_manager.get_file_path('spider.log')
        self.file_handler = logging.FileHandler(self.log_file_path, encoding='utf-8')
        self.file_handler.setLevel(logging.INFO)
        self.file_handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(name)s] %(levelname)s: %(message)s'
        ))

        # Add file handler to spider's logger and root scrapy logger
        spider.logger.logger.addHandler(self.file_handler)
        logging.getLogger('scrapy').addHandler(self.file_handler)

        spider.logger.info(f"Output directory: {self.output_dir}")
        spider.logger.info(f"Log file: {self.log_file_path}")

    def close_spider(self, spider):
        self.jobs_file.close()

        # Write summary
        summary = {
            'total_items': self.items_count,
            'timestamp': datetime.now().isoformat(),
            'output_dir': self.output_dir,
            'log_file': self.log_file_path
        }

        with open(os.path.join(self.output_dir, 'summary.json'), 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        spider.logger.info(f"Exported {self.items_count} items to {self.output_dir}")

        # Remove and close file handler
        spider.logger.logger.removeHandler(self.file_handler)
        logging.getLogger('scrapy').removeHandler(self.file_handler)
        self.file_handler.close()

    def process_item(self, item, spider):
        # Convert item to dict and write as JSON line
        item_dict = dict(item)

        # Remove HTML content for file export (keep it smaller)
        export_dict = {
            'job_id': item_dict.get('job_id'),
            'job_title': item_dict.get('job_title'),
            'business_name': item_dict.get('business_name'),
            'work_type': item_dict.get('work_type'),
            'job_type': item_dict.get('job_type'),
            'pay_range': item_dict.get('pay_range'),
            'suburb': item_dict.get('suburb'),
            'area': item_dict.get('area'),
            'region': item_dict.get('region'),
            'url': item_dict.get('url'),
            'advertiser_id': item_dict.get('advertiser_id'),
            'posted_date': item_dict.get('posted_date'),
            'scraped_at': datetime.now().isoformat()
        }

        line = json.dumps(export_dict, ensure_ascii=False)
        self.jobs_file.write(line + '\n')
        self.items_count += 1

        return item


class SeekspiderPipeline(object):

    def __init__(self):
        self.database_engine = getattr(config, 'DATABASE_ENGINE', 'postgres')
        self.table_name = getattr(config, 'DATABASE_TABLE', config.POSTGRESQL_TABLE)

    def _execute(self, query, params=()):
        sql = query
        if self.database_engine == 'sqlite':
            sql = sql.replace('%s', '?')
        self.cursor.execute(sql, params)

    def _resolve_sqlite_db_path(self):
        sqlite_db_path = getattr(config, 'SQLITE_DB_PATH', None)
        if not sqlite_db_path:
            raise ValueError('SQLITE_DB_PATH is required when DATABASE_ENGINE=sqlite')

        current_file = Path(__file__).resolve()
        project_root = current_file.parents[2]
        sqlite_path = Path(sqlite_db_path)
        if not sqlite_path.is_absolute():
            sqlite_path = project_root / sqlite_path
        return sqlite_path

    @classmethod
    def from_crawler(cls, crawler):
        # Create a pipeline instance
        instance = cls()
        # Connect the spider_closed signal
        crawler.signals.connect(instance.spider_closed, signal=signals.spider_closed)
        return instance

    def open_spider(self, spider):
        if self.database_engine == 'sqlite':
            db_manager = DatabaseManager(config)
            sqlite_path = db_manager.sqlite_db_path or self._resolve_sqlite_db_path()
            self.connection = sqlite3.connect(sqlite_path)
            spider.logger.info(f"Connected to database engine: sqlite ({sqlite_path})")
        else:
            self.connection = psycopg2.connect(
                host=config.POSTGRESQL_HOST,
                user=config.POSTGRESQL_USER,
                password=config.POSTGRESQL_PASSWORD,
                database=config.POSTGRESQL_DATABASE,
                port=config.POSTGRESQL_PORT
            )
            spider.logger.info("Connected to database engine: postgres")

        self.cursor = self.connection.cursor()

        if self.database_engine == 'postgres':
            self.cursor.execute("SET timezone = 'Australia/Perth'")

        # Store current region for later use in spider_closed
        self.current_region = getattr(spider, 'region', 'Perth')

        # Load job IDs for the current region into memory
        try:
            self._execute(
                f'SELECT "Id" FROM "{self.table_name}" WHERE "Region" = %s OR "Region" IS NULL',
                (self.current_region,)
            )
            self.existing_job_ids = set(str(row[0]) for row in self.cursor.fetchall())
            spider.logger.info(f"Loaded {len(self.existing_job_ids)} existing job IDs for region: {self.current_region}")
        except Exception as e:
            spider.logger.error(f"Error loading existing job IDs: {str(e)}")
            self.existing_job_ids = set()

    def close_spider(self, spider):
        # Remove this method as we'll close the connection in spider_closed
        pass

    def process_item(self, item, spider):
        job_id = str(item.get('job_id'))  # Convert to string to ensure consistent type comparison

        # Check if the job ID already exists in memory
        if job_id in self.existing_job_ids:
            spider.logger.info(f"Job ID: {job_id} already exists. Updating instead of inserting.")

            # Update existing job (JobDescription is handled by backfill script, not updated here)
            update_sql = """
                UPDATE "{}" SET
                    "JobTitle" = %s,
                    "BusinessName" = %s,
                    "WorkType" = %s,
                    "PayRange" = %s,
                    "Suburb" = %s,
                    "Area" = %s,
                    "Region" = %s,
                    "Url" = %s,
                    "AdvertiserId" = %s,
                    "JobType" = %s,
                    "UpdatedAt" = CURRENT_TIMESTAMP,
                    "PostedDate" = %s,
                    "ExpiryDate" = NULL,
                    "IsActive" = {}
                WHERE "Id" = %s
            """.format(self.table_name, 1 if self.database_engine == 'sqlite' else 'TRUE')

            try:
                advertiser_id = item.get('advertiser_id')
                if advertiser_id == "":
                    advertiser_id = None

                params = (
                    item.get('job_title'),
                    item.get('business_name'),
                    item.get('work_type'),
                    item.get('pay_range'),
                    item.get('suburb'),
                    item.get('area'),
                    item.get('region'),
                    item.get('url'),
                    advertiser_id,
                    item.get('job_type'),
                    item.get('posted_date'),
                    job_id
                )

                self._execute(update_sql, params)
                self.connection.commit()
                # spider.logger.info(f"Job ID: {job_id} updated successfully.")

            except Exception as e:
                self.connection.rollback()  # 回滚事务
                spider.logger.error(f"Error updating job {job_id}: {str(e)}")

            return item

        # Handle new job insertion
        # Note: JobDescription is NOT included - it's maintained by backfill script only
        insert_sql = """
            INSERT INTO "{}" (
                "Id",
                "JobTitle",
                "BusinessName",
                "WorkType",
                "PayRange",
                "Suburb",
                "Area",
                "Region",
                "Url",
                "AdvertiserId",
                "JobType",
                "CreatedAt",
                "UpdatedAt",
                "IsNew",
                "PostedDate"
            )
            VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,{},%s
            )
            """.format(self.table_name, 1 if self.database_engine == 'sqlite' else 'TRUE')

        try:
            advertiser_id = item.get('advertiser_id')
            if advertiser_id == "":
                advertiser_id = None

            params = (
                job_id,
                item.get('job_title'),
                item.get('business_name'),
                item.get('work_type'),
                item.get('pay_range'),
                item.get('suburb'),
                item.get('area'),
                item.get('region'),
                item.get('url'),
                advertiser_id,
                item.get('job_type'),
                item.get('posted_date')
            )

            self._execute(insert_sql, params)
            self.connection.commit()
            spider.logger.info(f"Job ID: {job_id} inserted successfully.")

            # Add the new job ID to the in-memory set
            self.existing_job_ids.add(job_id)

        except Exception as e:
            self.connection.rollback()  # 回滚事务
            spider.logger.error(f"Error inserting job {job_id}: {str(e)}")

        return item

    def spider_closed(self, spider):
        scraped_job_ids = spider.crawler.stats.get_value('scraped_job_ids', set())

        # 找出在数据库中但不在本次爬取中的职位ID（已过期的职位）
        # 只针对当前地区
        invalid_job_ids = self.existing_job_ids - scraped_job_ids

        if invalid_job_ids:
            spider.logger.info(f"Found {len(invalid_job_ids)} jobs not in current scrape for region: {self.current_region}")
            sample_invalid_jobs = list(invalid_job_ids)[:10]
            spider.logger.info(f"Sample of jobs not in current scrape: {sample_invalid_jobs}")

            id_placeholders = ', '.join(['%s'] * len(invalid_job_ids))
            is_active_true = 1 if self.database_engine == 'sqlite' else 'TRUE'
            is_active_false = 0 if self.database_engine == 'sqlite' else 'FALSE'

            # 将不存在的职位标记为失效（只针对当前地区）
            update_expired_sql = f'''
                UPDATE "{self.table_name}"
                SET "IsActive" = {is_active_false},
                    "UpdatedAt" = CURRENT_TIMESTAMP,
                    "ExpiryDate" = CURRENT_TIMESTAMP
                WHERE "Id" IN ({id_placeholders})
                AND "IsActive" = {is_active_true}
                AND ("Region" = %s OR "Region" IS NULL)
            '''

            params = [str(job_id) for job_id in invalid_job_ids]
            params.append(self.current_region)
            self._execute(update_expired_sql, tuple(params))
            expired_rows = self.cursor.rowcount
            self.connection.commit()
            spider.logger.info(f"Updated {expired_rows} jobs to IsActive=False for region: {self.current_region}")
        else:
            spider.logger.info(f"No expired jobs found for region: {self.current_region}")

        # 关闭数据库连接
        self.cursor.close()
        self.connection.close()
        spider.logger.info("Database connection closed")
