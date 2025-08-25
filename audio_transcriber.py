import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import customtkinter as ctk
import threading
import os
import time
import json
import tempfile
import math
import sys
from pathlib import Path
import logging
from openai import OpenAI
from mutagen import File as MutagenFile
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

# Log critical startup information
logging.info(f"Application starting...")
logging.info(f"Python executable: {sys.executable}")
logging.info(f"Current working directory: {os.getcwd()}")
logging.info(f"App is frozen: {getattr(sys, 'frozen', False)}")

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
            self.window.geometry("650x800")
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
        """Get audio duration using mutagen (no FFmpeg needed)"""
        try:
            abs_file_path = os.path.abspath(file_path)
            logging.info(f"Getting duration for file: {abs_file_path}")
            
            if not os.path.exists(abs_file_path):
                return None, f"Audio file does not exist: {abs_file_path}"
            
            # Use mutagen to read audio metadata
            audio_file = MutagenFile(abs_file_path)
            if audio_file and hasattr(audio_file, 'info') and hasattr(audio_file.info, 'length'):
                duration = audio_file.info.length
                logging.info(f"Audio duration: {duration:.2f} seconds ({duration/60:.1f} minutes)")
                return duration, None
            else:
                return None, "Could not read audio metadata"
                
        except Exception as e:
            error_msg = f"Failed to get audio duration: {str(e)}"
            logging.error(error_msg)
            return None, error_msg
    
    def needs_splitting(self, file_path):
        """Check if file needs splitting based on size and duration"""
        try:
            abs_file_path = os.path.abspath(file_path)
            
            # Check file size
            file_size_mb = os.path.getsize(abs_file_path) / (1024 * 1024)
            
            # Check duration using mutagen
            duration, error = self.get_audio_duration(abs_file_path)
            if error:
                logging.warning(f"Duration check failed, using size-only: {error}")
                # Estimate based on typical MP3 bitrate (128kbps = ~1MB per minute)
                estimated_duration = file_size_mb * 60  # rough estimate
                return file_size_mb > self.max_file_size_mb, file_size_mb, estimated_duration, None
            
            needs_split = file_size_mb > self.max_file_size_mb or duration > self.max_duration_seconds
            
            logging.info(f"File analysis: {file_size_mb:.1f}MB, {duration/60:.1f}min, needs_split: {needs_split}")
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
            config_path = os.path.abspath(self.config_file)
            
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    
                    # Load API key
                    saved_api_key = config.get('api_key', '')
                    if saved_api_key:
                        self.api_key.set(saved_api_key)
                        logging.info("Loaded saved API key")
                    
                    # Load output directory
                    saved_output_dir = config.get('output_directory', '')
                    if saved_output_dir and os.path.exists(saved_output_dir):
                        self.output_directory.set(os.path.abspath(saved_output_dir))
                        logging.info(f"Loaded saved output directory: {saved_output_dir}")
                        return
            
            # Fallback to desktop if no saved config or directory doesn't exist
            desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
            desktop_abs_path = os.path.abspath(desktop_path)
            self.output_directory.set(desktop_abs_path)
            logging.info(f"Using default output directory: {desktop_abs_path}")
            
        except Exception as e:
            # If there's any error loading config, use defaults
            desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
            desktop_abs_path = os.path.abspath(desktop_path)
            self.output_directory.set(desktop_abs_path)
            logging.warning(f"Error loading config, using defaults: {e}")
    
    def save_config(self):
        """Save current configuration to file"""
        try:
            config = {
                'api_key': self.api_key.get(),
                'output_directory': self.output_directory.get()
            }
            config_path = os.path.abspath(self.config_file)
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
            logging.info("Configuration saved")
        except Exception as e:
            logging.warning(f"Could not save configuration: {e}")
    
    def split_mp3_file(self, input_path, max_duration_seconds=1350):
        """Split MP3 file into chunks using pydub (no FFmpeg required)"""
        try:
            abs_input_path = os.path.abspath(input_path)
            logging.info(f"Splitting audio file: {abs_input_path}")
            
            # Load the audio file with pydub (works natively with MP3)
            audio = AudioSegment.from_file(abs_input_path)
            total_duration_ms = len(audio)
            total_duration_seconds = total_duration_ms / 1000.0
            
            # Calculate number of chunks needed
            num_chunks = math.ceil(total_duration_seconds / max_duration_seconds)
            
            chunks = []
            temp_dir = os.path.abspath(tempfile.gettempdir())
            
            logging.info(f"Splitting {total_duration_seconds:.1f}s audio into {num_chunks} chunks of max {max_duration_seconds}s each")
            
            for i in range(num_chunks):
                start_ms = i * max_duration_seconds * 1000
                end_ms = min((i + 1) * max_duration_seconds * 1000, total_duration_ms)
                
                # Extract chunk
                chunk = audio[start_ms:end_ms]
                chunk_duration_seconds = len(chunk) / 1000.0
                
                # Create temporary file for chunk
                chunk_filename = f"mp3_chunk_{int(time.time())}_{i+1}.mp3"
                chunk_path = os.path.join(temp_dir, chunk_filename)
                chunk_abs_path = os.path.abspath(chunk_path)
                
                logging.info(f"Creating chunk {i+1}: {chunk_abs_path}")
                
                # Export chunk as MP3 (pydub can do this without FFmpeg for MP3)
                chunk.export(chunk_abs_path, format="mp3", bitrate="128k")
                
                # Verify chunk was created
                if not os.path.exists(chunk_abs_path):
                    return None, f"Failed to create chunk {i+1} at {chunk_abs_path}"
                
                chunk_size_mb = os.path.getsize(chunk_abs_path) / (1024 * 1024)
                chunks.append(chunk_abs_path)
                self.temp_files.append(chunk_abs_path)
                
                logging.info(f"Created chunk {i+1}/{num_chunks}: {chunk_size_mb:.1f} MB, {chunk_duration_seconds:.1f}s")
            
            return chunks, None
            
        except Exception as e:
            error_msg = f"Failed to split audio: {str(e)}"
            logging.error(error_msg)
            import traceback
            logging.error(f"Full traceback: {traceback.format_exc()}")
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
                abs_filename = os.path.abspath(filename)
                
                file_extension = Path(abs_filename).suffix.lower().lstrip('.')
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
                file_size_mb = os.path.getsize(abs_filename) / (1024 * 1024)
                duration, duration_error = self.get_audio_duration(abs_filename)
                
                if duration_error:
                    logging.warning(f"Duration check failed: {duration_error}")
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
                        f"• Split into smaller chunks\n"
                        f"• All chunks transcribed and combined\n\n"
                        f"The original file will not be modified."
                    )
                
                self.audio_file_path.set(abs_filename)
                status_text = f"File selected: {Path(abs_filename).name} ({file_size_mb:.1f} MB, {duration_text})"
                self.status_label.configure(text=status_text)
                logging.info(f"Audio file selected: {abs_filename} ({file_size_mb:.1f} MB, {duration_text})")
                
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
                abs_directory = os.path.abspath(directory)
                self.output_directory.set(abs_directory)
                self.save_config()
                logging.info(f"Output directory selected and saved: {abs_directory}")
                
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
        
        abs_audio_path = os.path.abspath(self.audio_file_path.get())
        if not os.path.exists(abs_audio_path):
            messagebox.showerror("Error", f"The selected audio file does not exist: {abs_audio_path}")
            return False
        
        output_dir = self.output_directory.get()
        if not output_dir:
            messagebox.showerror("Error", "Please specify an output directory.")
            return False
        
        abs_output_dir = os.path.abspath(output_dir)
        if not os.path.exists(abs_output_dir):
            try:
                os.makedirs(abs_output_dir)
                logging.info(f"Created output directory: {abs_output_dir}")
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
            
            original_audio_path = os.path.abspath(self.audio_file_path.get())
            output_dir = os.path.abspath(self.output_directory.get())
            output_filename = self.output_filename.get()
            
            if not output_filename.lower().endswith('.txt'):
                output_filename += '.txt'
            
            output_path = os.path.join(output_dir, output_filename)
            
            logging.info(f"Starting transcription for: {original_audio_path}")
            logging.info(f"Output will be saved to: {output_path}")
            
            # Check if file needs processing (size or duration)
            needs_split, file_size_mb, duration, error = self.needs_splitting(original_audio_path)
            if error:
                self.update_status("Analysis failed")
                messagebox.showerror("File Analysis Error", error)
                return
            
            files_to_transcribe = []
            
            if needs_split:
                duration_minutes = duration / 60 if duration else 0
                self.update_status(f"File exceeds limits ({file_size_mb:.1f}MB, {duration_minutes:.1f}min), splitting...")
                self.update_progress(0.1)
                
                # Split the MP3 file (no FFmpeg needed)
                chunks, error = self.split_mp3_file(original_audio_path)
                if error:
                    self.update_status("Splitting failed")
                    messagebox.showerror("Splitting Error", f"Failed to split audio file:\n{error}")
                    return
                
                files_to_transcribe = chunks
                self.update_status(f"Split into {len(chunks)} chunks, transcribing...")
                logging.info(f"Audio split into {len(chunks)} chunks")
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
                    abs_file_path = os.path.abspath(file_path)
                    self.update_status(f"Transcribing chunk {i+1}/{total_files}...")
                    
                    logging.info(f"Transcribing file: {abs_file_path}")
                    logging.info(f"File exists: {os.path.exists(abs_file_path)}")
                    logging.info(f"File size: {os.path.getsize(abs_file_path)} bytes")
                    
                    with open(abs_file_path, "rb") as audio_file:
                        transcript = self.client.audio.transcriptions.create(
                            model="gpt-4o-transcribe",
                            file=audio_file
                        )
                    
                    all_transcripts.append(transcript.text)
                    
                    # Update progress
                    progress = 0.3 + (0.5 * (i + 1) / total_files)
                    self.update_progress(progress)
                    
                    logging.info(f"Transcribed chunk {i+1}/{total_files} successfully")
                    
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
