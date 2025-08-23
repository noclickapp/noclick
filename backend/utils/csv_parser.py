import csv
import io
import asyncio
from typing import List, Tuple, Dict, Any, Optional, Callable, Union
import pandas as pd
import numpy as np
import aiofiles
import chardet


class CSVParserError(Exception):
    """Custom exception for CSV parsing errors."""
    pass


class CSVParser:
    """
    A comprehensive asynchronous CSV parser class designed to handle non-standard CSV files.
    
    Expected irregularities handled:
      - Blank rows.
      - Rows with missing or extra columns.
      - Multiple tables in one file.
      - Missing or inconsistent headers.
      - Irregular cell contents.
      - Grouped tables separated by gaps in cells.
    
    The parser:
      1. Asynchronously reads the CSV file (or BytesIO object) with descriptive errors.
      2. Detects multiple tables.
      3. Converts each table into a pandas DataFrame.
      4. Standardizes the DataFrame values.
      5. Extracts rich metadata for each DataFrame.
    
    Parameters:
      - filepath: Path to the CSV file OR a BytesIO object containing CSV data.
      - unique_values_limit: Maximum number of unique values to return in metadata.
      - progress_callback: Optional asynchronous callback for progress updates 
                           (accepts a short string ending with '...').
    """
    DEFAULT_NULL_STRINGS = {"", "null", "none", "n/a", "na"}

    def __init__(
        self,
        filepath: Union[str, io.BytesIO],
        unique_values_limit: int = 50,
        progress_callback: Optional[Callable[[str], Any]] = None,
        null_strings: Optional[set] = None
    ):
        """
        Initialize the CSVParser.
        
        :param filepath: Path to the CSV file OR a BytesIO object containing CSV data.
        :param unique_values_limit: Maximum number of unique values to return in metadata.
        :param progress_callback: Optional async callback for progress updates.
        :param null_strings: A set of strings to interpret as null/missing.
        """
        self.filepath = filepath
        self.unique_values_limit = unique_values_limit
        self.progress_callback = progress_callback
        self.null_strings = null_strings if null_strings is not None else self.DEFAULT_NULL_STRINGS

    async def _progress(self, message: str) -> None:
        """
        Awaits the async progress callback (if provided) with the given message.
        
        :param message: The progress message.
        """
        if self.progress_callback:
            # Assume progress_callback is an async callable.
            await self.progress_callback(message)

    async def _read_csv_lines(self) -> List[List[str]]:
        """
        Asynchronously reads the CSV file or BytesIO object and returns a list of rows.
        
        :return: List of rows from the CSV data.
        :raises CSVParserError: When the file cannot be read.
        """
        await self._progress("Reading CSV file...")
        rows: List[List[str]] = []
        line_num = 0

        try:
            # Read raw bytes for encoding detection
            if isinstance(self.filepath, str):
                async with aiofiles.open(self.filepath, mode='rb') as f:
                    raw_bytes = await f.read()
            else:
                def read_buffer() -> bytes:
                    self.filepath.seek(0)
                    return self.filepath.read()
                raw_bytes = await asyncio.to_thread(read_buffer)

            # Detect encoding
            detected = chardet.detect(raw_bytes)
            encoding = detected.get("encoding") or "utf-8-sig"
            await self._progress(f"Detected encoding: {encoding}...")

            # Decode text with fallback and split into lines
            text = raw_bytes.decode(encoding, errors="replace")
            lines = text.splitlines()
            for row in csv.reader(lines):
                line_num += 1
                rows.append([cell.strip() for cell in row])
        except FileNotFoundError:
            raise CSVParserError(f"File not found: {self.filepath}")
        except csv.Error as e:
            raise CSVParserError(f"Error reading CSV file at line {line_num}: {e}")
        except Exception as e:
            raise CSVParserError(f"Unexpected error reading CSV file: {e}")

        if not rows:
            raise CSVParserError("The CSV file is empty.")

        await self._progress("CSV file read...")
        return rows

    def _is_empty_row(self, row: List[str]) -> bool:
        """
        Checks if a row is empty.
        
        :param row: List of strings representing a row.
        :return: True if the row is empty.
        """
        return all(cell.strip() == "" for cell in row)

    async def _detect_tables(self, rows: List[List[str]]) -> List[List[List[str]]]:
        """
        Splits the CSV content into multiple tables.
        
        :param rows: List of rows from the CSV.
        :return: A list of table blocks.
        :raises CSVParserError: When no valid tables are found.
        """
        await self._progress("Detecting tables...")
        tables: List[List[List[str]]] = []
        current_table: List[List[str]] = []

        for row in rows:
            if self._is_empty_row(row):
                if current_table:
                    tables.append(current_table)
                    current_table = []
            else:
                current_table.append(row)
        if current_table:
            tables.append(current_table)

        if not tables:
            raise CSVParserError("No valid table blocks found in the CSV file.")
        await self._progress("Tables detected...")
        return tables

    def _pad_row(self, row: List[str], target_length: int) -> List[str]:
        """
        Pads a row with empty strings.
        
        :param row: The original row.
        :param target_length: The required number of columns.
        :return: The padded row.
        """
        return row + [""] * (target_length - len(row))

    async def _create_dataframe(self, table: List[List[str]]) -> pd.DataFrame:
        """
        Creates a pandas DataFrame from a table block.
        
        :param table: A table block.
        :return: A pandas DataFrame.
        :raises CSVParserError: When a header row cannot be determined.
        """
        await self._progress("Creating DataFrame...")
        if not table:
            raise CSVParserError("Encountered an empty table block.")

        header = table[0]
        # Remove BOM from header cells, if present.
        header = [cell.lstrip("\ufeff") for cell in header]
        max_length = max(len(row) for row in table)

        if len(header) < max_length:
            header = header + [f"Unnamed_{i}" for i in range(len(header), max_length)]
        else:
            header = [col if col != "" else f"Unnamed_{idx}" for idx, col in enumerate(header)]

        data_rows: List[List[str]] = []
        for row in table[1:]:
            if len(row) < max_length:
                row = self._pad_row(row, max_length)
            elif len(row) > max_length:
                await self._progress("Truncating extra columns...")
                row = row[:max_length]
            data_rows.append(row)

        try:
            df = pd.DataFrame(data_rows, columns=header)
        except Exception as e:
            raise CSVParserError(f"Error creating DataFrame: {e}")

        await self._progress("DataFrame created...")
        return df

    def _standardize_cell(self, cell: str) -> Optional[str]:
        """
        Standardizes a cell by trimming, lower-casing, and mapping null strings.
        
        :param cell: The original cell value.
        :return: The standardized cell value or None.
        """
        cell = cell.strip()
        if cell.lower() in self.null_strings:
            return None
        return cell.lower()

    async def standardize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardizes the DataFrame by cleaning its string values.
        
        :param df: The original DataFrame.
        :return: The standardized DataFrame.
        """
        await self._progress("Standardizing data...")
        df = df.copy()
        for col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].apply(lambda x: self._standardize_cell(x) if isinstance(x, str) else x)
        await self._progress("Data standardized...")
        return df

    async def extract_metadata(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Extracts detailed metadata for each column.
        
        :param df: The standardized DataFrame.
        :return: A dictionary mapping each column to its metadata.
        """
        await self._progress("Extracting metadata...")
        metadata: Dict[str, Any] = {}
        for col in df.columns:
            col_meta: Dict[str, Any] = {}
            series = df[col]
            total = len(series)
            missing_count = int(series.isna().sum())
            non_null = total - missing_count

            col_meta["total_count"] = total
            col_meta["missing_count"] = missing_count
            col_meta["non_null_count"] = non_null

            series_numeric = pd.to_numeric(series, errors='coerce')
            if series_numeric.notna().sum() == non_null and non_null > 0:
                col_meta["dtype"] = "numeric"
                col_meta["min"] = float(series_numeric.min())
                col_meta["max"] = float(series_numeric.max())
                col_meta["mean"] = float(series_numeric.mean())
                col_meta["median"] = float(series_numeric.median())
                col_meta["std"] = float(series_numeric.std())
            else:
                col_meta["dtype"] = str(series.dtype)
                unique_values = series.dropna().unique().tolist()
                col_meta["unique_count"] = len(unique_values)
                if len(unique_values) <= self.unique_values_limit:
                    col_meta["unique_values"] = sorted(unique_values)
                else:
                    col_meta["unique_values_sample"] = sorted(unique_values)[:self.unique_values_limit]
            metadata[col] = col_meta
        await self._progress("Metadata extracted...")
        return metadata

    async def parse_csv(self) -> Tuple[List[pd.DataFrame], List[Dict[str, Any]]]:
        """
        Parses the CSV file and returns DataFrames and metadata.
        
        :return: A tuple (dataframes, metadata_list).
        :raises CSVParserError: For any issues during parsing.
        """
        await self._progress("Parsing CSV...")

        try:
            raw_rows = await self._read_csv_lines()
            table_blocks = await self._detect_tables(raw_rows)
        except CSVParserError as e:
            raise CSVParserError(f"Error during CSV reading/table detection: {e}")

        dataframes: List[pd.DataFrame] = []
        metadata_list: List[Dict[str, Any]] = []

        for table_idx, table in enumerate(table_blocks, start=1):
            await self._progress(f"Processing table #{table_idx}...")
            try:
                df = await self._create_dataframe(table)
            except CSVParserError as e:
                raise CSVParserError(f"Error processing table #{table_idx}: {e}")

            df = await self.standardize_dataframe(df)
            meta = await self.extract_metadata(df)

            dataframes.append(df)
            metadata_list.append(meta)
            await self._progress(f"Table #{table_idx} processed...")

        await self._progress("CSV parsing complete...")
        
        return dataframes, metadata_list