
import subprocess
import threading
import queue
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

class StreamingTranscoder:
    """
    Transcodes incoming audio chunks (e.g., WebM) to raw PCM 16kHz via ffmpeg.
    Designed for real-time streaming.
    """
    def __init__(self, input_format="webm", output_sample_rate=16000):
        self.input_format = input_format
        self.output_sample_rate = output_sample_rate
        self.process = None
        self.running = False
        self._output_queue = queue.Queue()
        self._read_thread = None

    def start(self):
        """Start the ffmpeg subprocess."""
        if self.running:
            return

        command = [
            "ffmpeg",
            "-i", "pipe:0",          # Read from stdin
            "-f", "s16le",           # Output format: Signed 16-bit Little Endian PCM
            "-acodec", "pcm_s16le",  # Audio codec
            "-ar", str(self.output_sample_rate), # Sample rate
            "-ac", "1",              # Channels: Mono
            "-v", "error",           # Only errors to reduce log noise
            "pipe:1"                 # Write to stdout
        ]
        
        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0  # No buffering for real-time
            )
            self.running = True
            
            # Start a thread to read stdout continuously
            self._read_thread = threading.Thread(target=self._read_stdout, daemon=True)
            self._read_thread.start()
            
            # Start a thread to read stderr for debugging
            self._error_thread = threading.Thread(target=self._read_stderr, daemon=True)
            self._error_thread.start()
            
            logger.info(f"[Transcoder] Started ffmpeg: {self.input_format} -> pcm_s16le @ {self.output_sample_rate}Hz")
            
        except Exception as e:
            logger.error(f"[Transcoder] Failed to start ffmpeg: {e}")
            self.running = False
            raise

    def process_chunk(self, chunk: bytes):
        """Write a chunk of input audio to ffmpeg's stdin."""
        if not self.running or not self.process:
            return
        try:
            self.process.stdin.write(chunk)
            self.process.stdin.flush()
        except Exception as e:
            logger.error(f"[Transcoder] Error writing chunk: {e}")
            self.stop()

    def _read_stdout(self):
        """Continuously read PCM data from ffmpeg's stdout."""
        chunk_size = 4096 # Read in 4KB blocks
        while self.running and self.process:
            try:
                data = self.process.stdout.read(chunk_size)
                if not data:
                    break
                # logger.debug(f"[Transcoder] Read {len(data)} bytes from stdout")
                self._output_queue.put(data)
            except Exception as e:
                logger.error(f"[Transcoder] Error reading output: {e}")
                break

    def _read_stderr(self):
        """Keep reading stderr to prevent buffer bloat and log errors."""
        while self.running and self.process:
            try:
                line = self.process.stderr.readline()
                if not line:
                    break
                line_str = line.decode('utf-8', errors='ignore').strip()
                if line_str and "debug" not in line_str.lower():
                    logger.debug(f"[Transcoder-FFMPEG] {line_str}")
            except Exception:
                break
        
    def get_exhaust_chunks(self):
        """Yields all available converted chunks from the queue."""
        while not self._output_queue.empty():
            yield self._output_queue.get()

    @staticmethod
    def calculate_rms(chunk: bytes) -> float:
        """Calculate the RMS (Root Mean Square) energy of a PCM S16LE chunk."""
        if not chunk:
            return 0
        
        import struct
        import math
        
        # s16le is 2 bytes per sample
        count = len(chunk) // 2
        if count == 0:
            return 0
            
        # Unpack as signed short (16-bit)
        try:
            format_str = f"<{count}h" 
            samples = struct.unpack(format_str, chunk)
            
            sum_squares = sum(s*s for s in samples)
            rms = math.sqrt(sum_squares / count)
            return rms
        except Exception as e:
            logger.debug(f"[Transcoder] RMS calc error: {e}")
            return 0

    def stop(self):
        """Stop the subprocess."""
        self.running = False
        if self.process:
            try:
                self.process.stdin.close()
                self.process.terminate()
                self.process.wait(timeout=1)
            except Exception as e:
                logger.warning(f"[Transcoder] Error stopping ffmpeg: {e}")
            finally:
                self.process = None
