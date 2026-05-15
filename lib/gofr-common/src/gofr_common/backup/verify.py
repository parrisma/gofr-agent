"""Backup verification module

Provides integrity checking for backup files using checksums.
"""

import hashlib
import logging
import tarfile
from pathlib import Path
from typing import Optional, Tuple


class BackupVerifier:
    """Verifies backup file integrity"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def calculate_checksum(self, filepath: Path, algorithm: str = 'sha256') -> str:
        """Calculate checksum of a file

        Args:
            filepath: Path to file
            algorithm: Hash algorithm (md5, sha1, sha256, sha512)

        Returns:
            Hexadecimal checksum string
        """
        hash_func = hashlib.new(algorithm)

        try:
            with open(filepath, 'rb') as f:
                # Read in chunks to handle large files
                for chunk in iter(lambda: f.read(8192), b''):
                    hash_func.update(chunk)

            checksum = hash_func.hexdigest()
            self.logger.debug(f"Calculated {algorithm} for {filepath.name}: {checksum}")
            return checksum

        except Exception as e:
            self.logger.error(f"Failed to calculate checksum for {filepath}: {e}")
            raise

    def save_checksum(self, filepath: Path, checksum: str) -> Path:
        """Save checksum to a .sha256 file alongside the backup

        Args:
            filepath: Path to backup file
            checksum: Checksum string

        Returns:
            Path to checksum file
        """
        checksum_file = filepath.with_suffix(filepath.suffix + '.sha256')

        try:
            with open(checksum_file, 'w') as f:
                f.write(f"{checksum}  {filepath.name}\n")

            self.logger.debug(f"Saved checksum to {checksum_file}")
            return checksum_file

        except Exception as e:
            self.logger.error(f"Failed to save checksum file: {e}")
            raise

    def verify_checksum(self, filepath: Path, expected_checksum: Optional[str] = None) -> bool:
        """Verify backup file checksum

        Args:
            filepath: Path to backup file
            expected_checksum: Expected checksum (if None, reads from .sha256 file)

        Returns:
            True if checksum matches, False otherwise
        """
        if expected_checksum is None:
            # Try to read from .sha256 file
            checksum_file = filepath.with_suffix(filepath.suffix + '.sha256')
            if not checksum_file.exists():
                self.logger.warning(f"No checksum file found for {filepath.name}")
                return False

            try:
                with open(checksum_file, 'r') as f:
                    line = f.readline().strip()
                    expected_checksum = line.split()[0]
            except Exception as e:
                self.logger.error(f"Failed to read checksum file: {e}")
                return False

        # Calculate actual checksum
        try:
            actual_checksum = self.calculate_checksum(filepath)

            if actual_checksum == expected_checksum:
                self.logger.info(f"Checksum verification passed for {filepath.name}")
                return True
            else:
                self.logger.error(
                    f"Checksum verification failed for {filepath.name}: "
                    f"expected {expected_checksum}, got {actual_checksum}"
                )
                return False

        except Exception as e:
            self.logger.error(f"Checksum verification error: {e}")
            return False

    def verify_tar_integrity(self, filepath: Path) -> Tuple[bool, Optional[str]]:
        """Verify tar archive can be opened and listed

        Args:
            filepath: Path to tar archive

        Returns:
            Tuple of (success, error_message)
        """
        try:
            # Try to open and list archive
            with tarfile.open(filepath, 'r:*') as tar:
                # List all members to verify structure
                members = tar.getmembers()
                file_count = len(members)

                self.logger.debug(f"Tar archive {filepath.name} contains {file_count} files")

                # Check for empty archive
                if file_count == 0:
                    return False, "Archive is empty"

                return True, None

        except tarfile.TarError as e:
            error_msg = f"Tar integrity check failed: {e}"
            self.logger.error(error_msg)
            return False, error_msg

        except Exception as e:
            error_msg = f"Failed to verify tar archive: {e}"
            self.logger.error(error_msg)
            return False, error_msg

    def verify_backup(self, filepath: Path, check_tar: bool = True) -> Tuple[bool, dict]:
        """Complete backup verification

        Args:
            filepath: Path to backup file
            check_tar: Whether to verify tar integrity

        Returns:
            Tuple of (success, details_dict)
        """
        results = {
            'filepath': str(filepath),
            'exists': filepath.exists(),
            'checksum_valid': False,
            'tar_valid': False,
            'errors': []
        }

        if not results['exists']:
            results['errors'].append("File does not exist")
            return False, results

        # Verify checksum
        try:
            results['checksum_valid'] = self.verify_checksum(filepath)
            if not results['checksum_valid']:
                results['errors'].append("Checksum verification failed")
        except Exception as e:
            results['errors'].append(f"Checksum error: {e}")

        # Verify tar integrity
        if check_tar and str(filepath).endswith(('.tar', '.tar.gz', '.tar.bz2', '.tar.xz')):
            try:
                tar_valid, tar_error = self.verify_tar_integrity(filepath)
                results['tar_valid'] = tar_valid
                if not tar_valid:
                    results['errors'].append(tar_error or "Tar verification failed")
            except Exception as e:
                results['errors'].append(f"Tar verification error: {e}")
        else:
            results['tar_valid'] = True  # Not a tar file or check skipped

        # Overall success
        success = results['checksum_valid'] and results['tar_valid']

        if success:
            self.logger.info(f"Backup verification passed: {filepath.name}")
        else:
            self.logger.warning(f"Backup verification failed: {filepath.name} - {results['errors']}")

        return success, results
