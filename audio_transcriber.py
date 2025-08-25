import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import customtkinter as ctk
import threading
import os
import time
import json
import subprocess
import tempfile
import math
import sys
from pathlib import Path
import logging
from openai import OpenAI
from pydub import AudioSegment

# Configure logging for troubleshooting
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('transcription_log.txt'),
        logging.StreamHandler()
    ]
)

# FFmpeg path handling for both development and packaged versions
def get_ffmpeg_path():
    """Get the correct ffmpeg path for both development and packaged executable"""
    if getattr(sys, 'frozen', False):
        # Running as packaged executable
        if hasattr(sys, '_MEIPASS'):
            # PyInstaller temp directory
            return os.path.join(sys._MEIPASS, 'ffmpeg.exe')
        else:
            # Fallback for other packagers
            return os.path.join(os.path.dirname(sys.executable), 'ffmpeg.exe')
    else:
        # Running as Python script in development
        return os.path.join(os.path.dirname(__file__), 'ffmpeg.exe')

def get_ffprobe_path():
    """Get the correct ffprobe path for both development and packaged executable"""
    if getattr(sys, 'frozen', False):
        # Running as packaged executable
        if hasattr(sys, '_MEIPASS'):
            # PyInstaller temp directory
            return os.path.join(sys._MEIPASS, 'ffprobe.exe')
        else:
            # Fallback for other packagers
            return os.path.join(os.path.dirname(sys.executable), 'ffprobe.exe')
    else:
        # Running as Python script in development
        return os.path.join(os.path.dirname(__file__), 'ffprobe.exe')

# Set the FFmpeg paths globally
FFMPEG_PATH = get_ffmpeg_path()
FFPROBE_PATH = get_ffprobe_path()

# Configure pydub to use our bundled ffmpeg
AudioSegment.converter = FFMPEG_PATH
AudioSegment.ffmpeg = FFMPEG_PATH
AudioSegment.ffprobe = FFPROBE_PATH

class AudioTranscriberApp:
    def __init__(self):
        try:
            # Configuration file path
            self.config_file = "transcriber_config.json"
            
            # Set appearance mode and color theme
            ctk.set_appearance_mode("light")
            ctk.set_default_color_theme("blue")
            
            # Initialize main window with larger size
            self.window = ctk.CTk()
            self.window.title("Audio Transcriber")
            self.window.geometry("650x800")  # Made taller for API key field
            self.window.resizable(True, True)
            
            # OpenAI limits
            self.max_file_size_mb = 25
            self.max_duration_seconds = 1400  # ~23 minutes
            
            # Variables
            self.api_key = tk.StringVar()
            self.audio_file_path = tk.StringVar()
            self.output_directory = tk.StringVar()
            self.output_filename = tk.StringVar()
            self.is_transcribing = False
            self.transcribed_text = ""
            self.temp_files = []  # Track all temporary files for cleanup
            self.client = None  # OpenAI client will be initialized when API key is set
            
            # Set default filename with DD_MM_YY_HH:MM format
            self.set_default_filename()
            
            # Load saved configuration or set defaults
            self.load_config()
            
            self.setup_ui()
            
            # Initialize OpenAI client if API key exists
            if self.api_key.get():
                self.initialize_openai_client()
            
            # Supported audio formats
            self.supported_formats = {
                'mp3', 'mp4', 'mpeg', 'mpga', 'm4a', 'wav', 'webm'
            }
            
        except Exception as e:
            logging.error(f"Critical error in initialization: {e}")
            messagebox.showerror("Startup Error", f"Failed to start application: {e}")
            raise
    
    def initialize_openai_client(self):
        """Initialize OpenAI client with current API key"""
        try:
            if self.api_key.get():
                self.client = OpenAI(api_key=self.api_key.get())
                logging.info("OpenAI client initialized successfully")
                return True
            return False
        except Exception as e:
            logging.error(f"Failed to initialize OpenAI client: {e}")
            self.client = None
            return False
    
    def validate_api_key(self):
        """Validate and save API key"""
        api_key = self.api_key.get().strip()
        if not api_key:
            messagebox.showerror("API Key Required", "Please enter your OpenAI API key.")
            return False
        
        if not api_key.startswith('sk-'):
            messagebox.showerror("Invalid API Key", "OpenAI API keys should start with 'sk-'.")
            return False
        
        # Test the API key by initializing client
        old_client = self.client
        if self.initialize_openai_client():
            # Save the working API key
            self.save_config()
            self.status_label.configure(text="API key validated and saved successfully")
            return True
        else:
            self.client = old_client
            messagebox.showerror("Invalid API Key", "Could not connect to OpenAI with this API key.")
            return False
    
    def get_audio_duration(self, file_path):
        """Get audio duration in seconds using pydub"""
        try:
            # Ensure both ffmpeg and ffprobe are set
            AudioSegment.converter = FFMPEG_PATH
            AudioSegment.ffmpeg = FFMPEG_PATH  
            AudioSegment.ffprobe = FFPROBE_PATH
            
            # Log paths for debugging
            logging.info(f"FFmpeg path: {FFMPEG_PATH}")
            logging.info(f"FFprobe path: {FFPROBE_PATH}")
            logging.info(f"FFmpeg exists: {os.path.exists(FFMPEG_PATH)}")
            logging.info(f"FFprobe exists: {os.path.exists(FFPROBE_PATH)}")
            
            audio = AudioSegment.from_file(file_path)
            duration_seconds = len(audio) / 1000.0  # Convert milliseconds to seconds
            return duration_seconds, None
            
        except Exception as e:
            error_msg = f"Failed to get audio duration: {str(e)}"
            logging.error(error_msg)
            # Fallback: Skip duration checking for this file
            return None, error_msg
    
    def needs_splitting(self, file_path):
        """Check if file needs splitting based on size and duration"""
        try:
            # Check file size
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            
            # Check duration
            duration, error = self.get_audio_duration(file_path)
            if error:
                return False, file_size_mb, None, error
            
            needs_split = file_size_mb > self.max_file_size_mb or duration > self.max_duration_seconds
            
            return needs_split, file_size_mb, duration, None
            
        except Exception as e:
            return False, 0, 0, f"Error checking file: {str(e)}"
    
    def set_default_filename(self):
        """Set default filename with DD_MM_YY_HH:MM format"""
        now = time.localtime()
        default_name = f"transcription_{now.tm_mday:02d}_{now.tm_mon:02d}_{now.tm_year % 100:02d}_{now.tm_hour:02d}:{now.tm_min:02d}"
        self.output_filename.set(default_name)
    
    def load_config(self):
        """Load configuration from file or set defaults"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    
                    # Load API key
                    saved_api_key = config.get('api_key', '')
                    if saved_api_key:
                        self.api_key.set(saved_api_key)
                        logging.info("Loaded saved API key")
                    
                    # Load output directory
                    saved_output_dir = config.get('output_directory', '')
                    if saved_output_dir and os.path.exists(saved_output_dir):
                        self.output_directory.set(saved_output_dir)
                        logging.info(f"Loaded saved output directory: {saved_output_dir}")
                        return
            
            # Fallback to desktop if no saved config or directory doesn't exist
            desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
            self.output_directory.set(desktop_path)
            logging.info(f"Using default output directory: {desktop_path}")
            
        except Exception as e:
            # If there's any error loading config, use defaults
            desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
            self.output_directory.set(desktop_path)
            logging.warning(f"Error loading config, using defaults: {e}")
    
    def save_config(self):
        """Save current configuration to file"""
        try:
            config = {
                'api_key': self.api_key.get(),
                'output_directory': self.output_directory.get()
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
            logging.info("Configuration saved")
        except Exception as e:
            logging.warning(f"Could not save configuration: {e}")
    
    def compress_audio(self, input_path, output_path):
        """Compress audio to MP3 64kbps mono using bundled ffmpeg"""
        try:
            cmd = [
                FFMPEG_PATH,  # Use bundled ffmpeg
                "-i", input_path,
                "-ac", "1",  # Mono
                "-b:a", "64k",  # 64kbps bitrate
                "-y",  # Overwrite output file
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, 
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            
            if result.returncode != 0:
                logging.error(f"ffmpeg compression failed: {result.stderr}")
                return False, f"Compression failed: {result.stderr}"
            
            compressed_size = os.path.getsize(output_path) / (1024 * 1024)
            
            # Also check duration after compression
            duration, duration_error = self.get_audio_duration(output_path)
            if duration_error:
                return False, f"Could not verify compressed file duration: {duration_error}"
            
            if compressed_size > self.max_file_size_mb or duration > self.max_duration_seconds:
                return False, f"Compressed file still exceeds limits: {compressed_size:.1f}MB, {duration:.1f}s"
            
            logging.info(f"Audio compressed successfully: {compressed_size:.1f} MB, {duration:.1f} seconds")
            return True, {"size": compressed_size, "duration": duration}
            
        except FileNotFoundError:
            return False, "FFmpeg not found. Please contact support."
        except Exception as e:
            return False, f"Compression error: {str(e)}"
    
    def split_audio_file(self, input_path, max_size_mb=24, max_duration_seconds=1350):
        """Split audio file into chunks using pydub, respecting both size and duration limits"""
        try:
            # Load the audio file
            audio = AudioSegment.from_file(input_path)
            total_duration_ms = len(audio)
            total_duration_seconds = total_duration_ms / 1000.0
            
            # Calculate chunk duration based on the more restrictive limit
            max_chunk_duration_ms = min(max_duration_seconds * 1000, 
                                      (max_size_mb * 1024 * 1024 * 1000) // 8192)  # Approximate for 64kbps
            
            # Calculate number of chunks needed
            num_chunks = math.ceil(total_duration_ms / max_chunk_duration_ms)
            
            chunks = []
            temp_dir = tempfile.gettempdir()
            
            logging.info(f"Splitting {total_duration_seconds:.1f}s audio into {num_chunks} chunks of max {max_chunk_duration_ms/1000:.1f}s each")
            
            for i in range(num_chunks):
                start_ms = i * max_chunk_duration_ms
                end_ms = min((i + 1) * max_chunk_duration_ms, total_duration_ms)
                
                # Extract chunk
                chunk = audio[start_ms:end_ms]
                chunk_duration_seconds = len(chunk) / 1000.0
                
                # Create temporary file for chunk
                chunk_filename = f"audio_chunk_{int(time.time())}_{i+1}.mp3"
                chunk_path = os.path.join(temp_dir, chunk_filename)
                
                # Export chunk as compressed MP3
                chunk.export(
                    chunk_path,
                    format="mp3",
                    bitrate="64k",
                    parameters=["-ac", "1"]  # Force mono
                )
                
                # Verify chunk meets both size and duration limits
                chunk_size_mb = os.path.getsize(chunk_path) / (1024 * 1024)
                
                if chunk_size_mb > self.max_file_size_mb or chunk_duration_seconds > self.max_duration_seconds:
                    # If still too large, try with lower bitrate
                    os.remove(chunk_path)
                    chunk.export(
                        chunk_path,
                        format="mp3",
                        bitrate="32k",
                        parameters=["-ac", "1"]
                    )
                    chunk_size_mb = os.path.getsize(chunk_path) / (1024 * 1024)
                    
                    # Final check
                    if chunk_size_mb > self.max_file_size_mb or chunk_duration_seconds > self.max_duration_seconds:
                        return None, f"Unable to create valid chunks. Chunk {i+1} is still {chunk_size_mb:.1f}MB, {chunk_duration_seconds:.1f}s"
                
                chunks.append(chunk_path)
                self.temp_files.append(chunk_path)
                
                logging.info(f"Created chunk {i+1}/{num_chunks}: {chunk_size_mb:.1f} MB, {chunk_duration_seconds:.1f}s")
            
            return chunks, None
            
        except Exception as e:
            error_msg = f"Failed to split audio: {str(e)}"
            logging.error(error_msg)
            return None, error_msg
    
    def setup_ui(self):
        try:
            # Configure window grid
            self.window.grid_rowconfigure(0, weight=1)
            self.window.grid_columnconfigure(0, weight=1)
            
            # Main scrollable frame instead of regular frame
            main_frame = ctk.CTkScrollableFrame(
                self.window,
                corner_radius=0,
                fg_color="transparent"
            )
            main_frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
            
            # Title
            title_label = ctk.CTkLabel(
                main_frame, 
                text="Audio Transcriber", 
                font=ctk.CTkFont(size=28, weight="bold")
            )
            title_label.pack(pady=(20, 30))
            
            # Subtitle
            subtitle_label = ctk.CTkLabel(
                main_frame, 
                text="Convert your audio files to text quickly and easily",
                font=ctk.CTkFont(size=14),
                text_color="gray"
            )
            subtitle_label.pack(pady=(0, 30))
            
            # API Key section
            api_frame = ctk.CTkFrame(main_frame)
            api_frame.pack(fill="x", padx=20, pady=10)
            
            api_label = ctk.CTkLabel(
                api_frame, 
                text="OpenAI API Key:",
                font=ctk.CTkFont(size=16, weight="bold")
            )
            api_label.pack(anchor="w", padx=15, pady=(15, 5))
            
            api_key_frame = ctk.CTkFrame(api_frame)
            api_key_frame.pack(fill="x", padx=15, pady=(0, 10))
            
            self.api_key_entry = ctk.CTkEntry(
                api_key_frame,
                textvariable=self.api_key,
                placeholder_text="Enter your OpenAI API key (sk-...)",
                show="*",  # Hide the API key
                font=ctk.CTkFont(size=12)
            )
            self.api_key_entry.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=10)
            
            validate_key_btn = ctk.CTkButton(
                api_key_frame,
                text="Save Key",
                command=self.validate_api_key,
                width=80
            )
            validate_key_btn.pack(side="right", padx=(5, 10), pady=10)
            
            # Show/Hide API key button
            self.show_key_btn = ctk.CTkButton(
                api_frame,
                text="Show API Key",
                command=self.toggle_api_key_visibility,
                width=120,
                height=25
            )
            self.show_key_btn.pack(padx=15, pady=(0, 15))
            
            # Audio file selection section
            audio_frame = ctk.CTkFrame(main_frame)
            audio_frame.pack(fill="x", padx=20, pady=10)
            
            audio_label = ctk.CTkLabel(
                audio_frame, 
                text="1. Select Audio File:",
                font=ctk.CTkFont(size=16, weight="bold")
            )
            audio_label.pack(anchor="w", padx=15, pady=(15, 5))
            
            audio_path_frame = ctk.CTkFrame(audio_frame)
            audio_path_frame.pack(fill="x", padx=15, pady=(0, 15))
            
            self.audio_path_entry = ctk.CTkEntry(
                audio_path_frame,
                textvariable=self.audio_file_path,
                placeholder_text="No file selected...",
                state="readonly",
                font=ctk.CTkFont(size=12)
            )
            self.audio_path_entry.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=10)
            
            audio_browse_btn = ctk.CTkButton(
                audio_path_frame,
                text="Browse",
                command=self.browse_audio_file,
                width=80
            )
            audio_browse_btn.pack(side="right", padx=(5, 10), pady=10)
            
            # Output directory section
            output_frame = ctk.CTkFrame(main_frame)
            output_frame.pack(fill="x", padx=20, pady=10)
            
            output_label = ctk.CTkLabel(
                output_frame,
                text="2. Choose Output Location:",
                font=ctk.CTkFont(size=16, weight="bold")
            )
            output_label.pack(anchor="w", padx=15, pady=(15, 5))
            
            # Output folder section
            output_folder_frame = ctk.CTkFrame(output_frame)
            output_folder_frame.pack(fill="x", padx=15, pady=(0, 10))
            
            folder_label = ctk.CTkLabel(
                output_folder_frame,
                text="Folder:",
                font=ctk.CTkFont(size=12, weight="bold")
            )
            folder_label.pack(side="left", padx=(10, 5), pady=10)
            
            self.output_path_entry = ctk.CTkEntry(
                output_folder_frame,
                textvariable=self.output_directory,
                font=ctk.CTkFont(size=12)
            )
            self.output_path_entry.pack(side="left", fill="x", expand=True, padx=(5, 5), pady=10)
            
            output_browse_btn = ctk.CTkButton(
                output_folder_frame,
                text="Browse",
                command=self.browse_output_directory,
                width=80
            )
            output_browse_btn.pack(side="right", padx=(5, 10), pady=10)
            
            # Output filename section
            output_filename_frame = ctk.CTkFrame(output_frame)
            output_filename_frame.pack(fill="x", padx=15, pady=(0, 15))
            
            filename_label = ctk.CTkLabel(
                output_filename_frame,
                text="Filename:",
                font=ctk.CTkFont(size=12, weight="bold")
            )
            filename_label.pack(side="left", padx=(10, 5), pady=10)
            
            self.output_filename_entry = ctk.CTkEntry(
                output_filename_frame,
                textvariable=self.output_filename,
                font=ctk.CTkFont(size=12)
            )
            self.output_filename_entry.pack(side="left", fill="x", expand=True, padx=(5, 5), pady=10)
            
            refresh_filename_btn = ctk.CTkButton(
                output_filename_frame,
                text="Reset",
                command=self.set_default_filename,
                width=60
            )
            refresh_filename_btn.pack(side="right", padx=(5, 10), pady=10)
            
            # Transcribe section
            transcribe_frame = ctk.CTkFrame(main_frame)
            transcribe_frame.pack(fill="x", padx=20, pady=20)
            
            transcribe_label = ctk.CTkLabel(
                transcribe_frame,
                text="3. Start Transcription:",
                font=ctk.CTkFont(size=16, weight="bold")
            )
            transcribe_label.pack(anchor="w", padx=15, pady=(15, 10))
            
            # Progress bar
            self.progress_bar = ctk.CTkProgressBar(transcribe_frame)
            self.progress_bar.pack(fill="x", padx=15, pady=(0, 10))
            self.progress_bar.set(0)
            
            # Status label
            self.status_label = ctk.CTkLabel(
                transcribe_frame,
                text="Ready to transcribe",
                font=ctk.CTkFont(size=12),
                text_color="gray"
            )
            self.status_label.pack(padx=15, pady=(0, 10))
            
            # Button frame for transcribe and copy buttons
            button_frame = ctk.CTkFrame(transcribe_frame)
            button_frame.pack(fill="x", padx=15, pady=(0, 15))
            
            # Transcribe button
            self.transcribe_btn = ctk.CTkButton(
                button_frame,
                text="Transcribe Audio",
                command=self.start_transcription,
                font=ctk.CTkFont(size=16, weight="bold"),
                height=40
            )
            self.transcribe_btn.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=10)
            
            # Copy to clipboard button (initially hidden)
            self.copy_btn = ctk.CTkButton(
                button_frame,
                text="Copy to Clipboard",
                command=self.copy_to_clipboard,
                font=ctk.CTkFont(size=14, weight="bold"),
                height=40,
                fg_color="green",
                hover_color="darkgreen"
            )
            
        except Exception as e:
            logging.error(f"Error setting up UI: {e}")
            raise
    
    def toggle_api_key_visibility(self):
        """Toggle between showing and hiding the API key"""
        if self.api_key_entry.cget("show") == "*":
            self.api_key_entry.configure(show="")
            self.show_key_btn.configure(text="Hide API Key")
        else:
            self.api_key_entry.configure(show="*")
            self.show_key_btn.configure(text="Show API Key")
    
    def browse_audio_file(self):
        try:
            file_types = [
                ("Audio Files", "*.mp3 *.mp4 *.mpeg *.mpga *.m4a *.wav *.webm"),
                ("All Files", "*.*")
            ]
            
            filename = filedialog.askopenfilename(
                title="Select Audio File",
                filetypes=file_types
            )
            
            if filename:
                file_extension = Path(filename).suffix.lower().lstrip('.')
                if file_extension not in self.supported_formats:
                    response = messagebox.askyesno(
                        "Unsupported Format",
                        f"The file format '.{file_extension}' might not be supported.\n"
                        f"Supported formats: {', '.join(self.supported_formats)}\n\n"
                        "Do you want to try anyway?"
                    )
                    if not response:
                        return
                
                # Check both file size and duration
                file_size_mb = os.path.getsize(filename) / (1024 * 1024)
                duration, duration_error = self.get_audio_duration(filename)
                
                if duration_error:
                    messagebox.showwarning("Duration Check Failed", f"Could not determine audio duration:\n{duration_error}")
                    duration_text = "unknown duration"
                else:
                    duration_minutes = duration / 60
                    duration_text = f"{duration_minutes:.1f} min"
                
                if file_size_mb > self.max_file_size_mb or (duration and duration > self.max_duration_seconds):
                    limit_text = f"OpenAI limits: {self.max_file_size_mb}MB or {self.max_duration_seconds/60:.1f} minutes"
                    messagebox.showinfo(
                        "Large File Detected", 
                        f"Selected file: {file_size_mb:.1f} MB, {duration_text}\n"
                        f"Limits: {limit_text}\n\n"
                        f"Large files will be automatically processed:\n"
                        f"• First compressed to 64kbps MP3 mono\n"
                        f"• If still over limits, split into chunks\n"
                        f"• All chunks transcribed and combined\n\n"
                        f"The original file will not be modified."
                    )
                
                self.audio_file_path.set(filename)
                status_text = f"File selected: {Path(filename).name} ({file_size_mb:.1f} MB, {duration_text})"
                self.status_label.configure(text=status_text)
                logging.info(f"Audio file selected: {Path(filename).name} ({file_size_mb:.1f} MB, {duration_text})")
                
        except Exception as e:
            logging.error(f"Error browsing audio file: {e}")
            messagebox.showerror("Error", f"Error selecting file: {e}")
    
    def browse_output_directory(self):
        try:
            directory = filedialog.askdirectory(
                title="Select Output Directory",
                initialdir=self.output_directory.get()
            )
            
            if directory:
                self.output_directory.set(directory)
                self.save_config()
                logging.info(f"Output directory selected and saved: {directory}")
                
        except Exception as e:
            logging.error(f"Error browsing output directory: {e}")
            messagebox.showerror("Error", f"Error selecting directory: {e}")
    
    def copy_to_clipboard(self):
        try:
            if self.transcribed_text:
                self.window.clipboard_clear()
                self.window.clipboard_append(self.transcribed_text)
                self.window.update()
                
                original_text = self.copy_btn.cget("text")
                self.copy_btn.configure(text="Copied! ✓")
                self.window.after(2000, lambda: self.copy_btn.configure(text=original_text))
                
                logging.info("Transcription copied to clipboard")
            else:
                messagebox.showwarning("No Text", "No transcription available to copy.")
        except Exception as e:
            logging.error(f"Error copying to clipboard: {e}")
            messagebox.showerror("Error", f"Error copying to clipboard: {e}")
    
    def cleanup_temp_files(self):
        """Clean up all temporary files"""
        for temp_file in self.temp_files:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                    logging.info(f"Cleaned up temporary file: {temp_file}")
                except Exception as e:
                    logging.warning(f"Could not clean up temporary file {temp_file}: {e}")
        self.temp_files = []
    
    def validate_inputs(self):
        # Check if API key is set and client is initialized
        if not self.api_key.get() or not self.client:
            messagebox.showerror("API Key Required", "Please enter and save your OpenAI API key first.")
            return False
            
        if not self.audio_file_path.get():
            messagebox.showerror("Error", "Please select an audio file.")
            return False
        
        if not os.path.exists(self.audio_file_path.get()):
            messagebox.showerror("Error", "The selected audio file does not exist.")
            return False
        
        output_dir = self.output_directory.get()
        if not output_dir:
            messagebox.showerror("Error", "Please specify an output directory.")
            return False
        
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
                logging.info(f"Created output directory: {output_dir}")
            except Exception as e:
                messagebox.showerror("Error", f"Cannot create output directory: {e}")
                return False
        
        filename = self.output_filename.get().strip()
        if not filename:
            messagebox.showerror("Error", "Please specify a filename.")
            return False
        
        if not filename.lower().endswith('.txt'):
            filename += '.txt'
            self.output_filename.set(filename)
        
        return True
    
    def start_transcription(self):
        if self.is_transcribing:
            return
        
        if not self.validate_inputs():
            return
        
        self.copy_btn.pack_forget()
        self.is_transcribing = True
        self.transcribe_btn.configure(text="Transcribing...", state="disabled")
        self.progress_bar.set(0)
        
        thread = threading.Thread(target=self.transcribe_audio)
        thread.daemon = True
        thread.start()
    
    def transcribe_audio(self):
        try:
            self.update_status("Analyzing audio file...")
            self.update_progress(0.05)
            
            original_audio_path = self.audio_file_path.get()
            output_dir = self.output_directory.get()
            output_filename = self.output_filename.get()
            
            if not output_filename.lower().endswith('.txt'):
                output_filename += '.txt'
            
            output_path = os.path.join(output_dir, output_filename)
            
            # Check if file needs processing (size or duration)
            needs_split, file_size_mb, duration, error = self.needs_splitting(original_audio_path)
            if error:
                self.update_status("Analysis failed")
                messagebox.showerror("File Analysis Error", error)
                return
            
            files_to_transcribe = []
            
            if needs_split:
                duration_minutes = duration / 60 if duration else 0
                self.update_status(f"File exceeds limits ({file_size_mb:.1f}MB, {duration_minutes:.1f}min), processing...")
                self.update_progress(0.1)
                
                # Try compression first
                temp_dir = tempfile.gettempdir()
                temp_compressed = os.path.join(temp_dir, f"compressed_audio_{int(time.time())}.mp3")
                self.temp_files.append(temp_compressed)
                
                success, result = self.compress_audio(original_audio_path, temp_compressed)
                
                if success:
                    compressed_info = result
                    compressed_size = compressed_info["size"]
                    compressed_duration = compressed_info["duration"]
                    
                    if compressed_size <= self.max_file_size_mb and compressed_duration <= self.max_duration_seconds:
                        # Compression worked, use compressed file
                        files_to_transcribe = [temp_compressed]
                        self.update_status(f"Compressed to {compressed_size:.1f}MB, {compressed_duration/60:.1f}min - uploading to OpenAI...")
                        logging.info(f"Audio compressed from {file_size_mb:.1f}MB/{duration/60:.1f}min to {compressed_size:.1f}MB/{compressed_duration/60:.1f}min")
                    else:
                        # Still exceeds limits, need to split
                        self.update_status("Still exceeds limits, splitting into chunks...")
                        self.update_progress(0.15)
                        
                        chunks, error = self.split_audio_file(temp_compressed)
                        if error:
                            self.update_status("Splitting failed")
                            messagebox.showerror("Splitting Error", f"Failed to split audio file:\n{error}")
                            return
                        
                        files_to_transcribe = chunks
                        self.update_status(f"Split into {len(chunks)} chunks, transcribing...")
                        logging.info(f"Audio split into {len(chunks)} chunks")
                else:
                    # Compression failed, try splitting original
                    self.update_status("Compression failed, splitting original file...")
                    self.update_progress(0.15)
                    
                    chunks, error = self.split_audio_file(original_audio_path)
                    if error:
                        self.update_status("Processing failed")
                        messagebox.showerror("Processing Error", f"Failed to process audio file:\n{error}")
                        return
                    
                    files_to_transcribe = chunks
                    self.update_status(f"Split into {len(chunks)} chunks, transcribing...")
            else:
                # File is within limits, use as-is
                files_to_transcribe = [original_audio_path]
                self.update_status("File within limits, uploading to OpenAI...")
            
            self.update_progress(0.3)
            
            # Transcribe all files
            all_transcripts = []
            total_files = len(files_to_transcribe)
            
            for i, file_path in enumerate(files_to_transcribe):
                try:
                    self.update_status(f"Transcribing chunk {i+1}/{total_files}...")
                    
                    with open(file_path, "rb") as audio_file:
                        transcript = self.client.audio.transcriptions.create(
                            model="gpt-4o-transcribe",
                            file=audio_file
                        )
                    
                    all_transcripts.append(transcript.text)
                    
                    # Update progress
                    progress = 0.3 + (0.5 * (i + 1) / total_files)
                    self.update_progress(progress)
                    
                    logging.info(f"Transcribed chunk {i+1}/{total_files}")
                    
                except Exception as e:
                    logging.error(f"Failed to transcribe chunk {i+1}: {e}")
                    all_transcripts.append(f"[Error transcribing chunk {i+1}: {str(e)}]")
            
            self.update_progress(0.8)
            self.update_status("Combining transcripts and saving...")
            
            # Combine all transcripts
            if len(all_transcripts) == 1:
                combined_transcript = all_transcripts[0]
            else:
                # Add chunk separators for clarity
                combined_transcript = ""
                for i, transcript in enumerate(all_transcripts):
                    if i > 0:
                        combined_transcript += f"\n\n--- Part {i+1} ---\n\n"
                    combined_transcript += transcript
            
            self.transcribed_text = combined_transcript
            
            # Save to file
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(combined_transcript)
            
            self.update_progress(1.0)
            self.update_status("Transcription completed successfully!")
            
            if total_files > 1:
                logging.info(f"Transcription completed: {total_files} chunks combined into {output_filename}")
            else:
                logging.info(f"Transcription completed: {output_filename}")
            
            self.window.after(0, self.show_copy_button)
            
            response = messagebox.askyesno(
                "Success!", 
                f"Transcription completed successfully!\n\n"
                f"File saved as: {output_filename}\n"
                f"Location: {output_dir}\n"
                f"{'Processed from ' + str(total_files) + ' chunks' if total_files > 1 else ''}\n\n"
                "Would you like to open the output folder?"
            )
            
            if response:
                if os.name == 'nt':  # Windows
                    os.startfile(output_dir)
                elif os.name == 'posix':  # macOS and Linux
                    os.system(f'open "{output_dir}"')
            
        except Exception as e:
            error_msg = str(e)
            logging.error(f"Transcription error: {error_msg}")
            
            self.update_status("Transcription failed")
            self.update_progress(0)
            
            if "rate limit" in error_msg.lower():
                messagebox.showerror(
                    "Rate Limit Exceeded",
                    "Too many requests to OpenAI. Please wait a moment and try again."
                )
            elif "authentication" in error_msg.lower() or "api" in error_msg.lower():
                messagebox.showerror(
                    "API Error",
                    "There's an issue with the API key or connection. Please check your API key."
                )
            else:
                messagebox.showerror(
                    "Transcription Error",
                    f"An error occurred during transcription:\n{error_msg[:200]}..."
                )
        
        finally:
            self.cleanup_temp_files()
            self.is_transcribing = False
            self.window.after(0, self.reset_ui)
    
    def show_copy_button(self):
        """Show the copy button after successful transcription"""
        self.copy_btn.pack(side="right", fill="x", expand=True, padx=(5, 10), pady=10)
    
    def update_status(self, message):
        self.window.after(0, lambda: self.status_label.configure(text=message))
    
    def update_progress(self, value):
        self.window.after(0, lambda: self.progress_bar.set(value))
    
    def reset_ui(self):
        self.transcribe_btn.configure(text="Transcribe Audio", state="normal")
    
    def run(self):
        try:
            self.window.mainloop()
        except Exception as e:
            logging.error(f"Application error: {e}")

def main():
    try:
        app = AudioTranscriberApp()
        app.run()
    except Exception as e:
        logging.error(f"Failed to start application: {e}")
        messagebox.showerror("Startup Error", f"Failed to start application: {e}")

if __name__ == "__main__":
    main()
