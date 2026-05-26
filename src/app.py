import os
import sys
import traceback
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
import threading
import platform
import webbrowser
from src.config import AppConfig
from src.hf_engine import HuggingFaceEngine
from huggingface_hub import snapshot_download
from src.utils import check_ollama_installed, get_ollama_version, is_ollama_running

def global_exception_handler(exctype, value, tb):
    stack = traceback.format_exception(exctype, value, tb)
    error_msg = "".join(stack)
    with open("crash_log.txt", "a") as f:
        f.write(f"\n--- CRASH AT {tk.datetime.datetime.now()} ---\n")
        f.write(error_msg)
    # Still print to stderr for visibility in terminal
    sys.__stderr__.write(error_msg)

import datetime
tk.datetime = datetime # Inject for the handler
sys.excepthook = global_exception_handler

# Load Configuration
config = AppConfig()

class GGUFConverterApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(config.get("ui.title", "GEMMA FORGE"))
        self.geometry(config.get("ui.window_size", "1000x800"))
        set_appearance_mode(config.get("ui.theme", "dark"))
        set_default_color_theme(config.get("ui.color", "blue"))

        # Set window background color
        self.configure(fg_color=config.get("ui.bg_color", "#1a1a1a"))

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- Top Branding Header ---
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.grid(row=0, column=0, padx=20, pady=(20, 0), sticky="ew")
        
        # App Logo (Emoji as placeholder for modern look)
        self.logo_label = ctk.CTkLabel(self.header_frame, text="⚒️", font=("Arial", 32))
        self.logo_label.pack(side="left", padx=10)
        
        # Styled Title
        self.title_label = ctk.CTkLabel(
            self.header_frame, 
            text=config.get("ui.title", "GEMMA FORGE"), 
            font=("Impact", 32, "bold"),
            text_color=config.get("ui.accent_color", "#3b8ed0")
        )
        self.title_label.pack(side="left", padx=10)

        self.tagline_label = ctk.CTkLabel(
            self.header_frame, 
            text="Forging the path to local AI.", 
            font=("Arial", 14, "italic"),
            text_color="gray"
        )
        self.tagline_label.pack(side="left", padx=20)

        # --- Ollama Environment Check ---
        # We define a small helper to handle logs during early init
        def early_log(msg):
            print(f"[INIT] {msg}")

        early_log(f"Initializing system check... {platform.system()} {platform.release()}")
        if not check_ollama_installed():
            early_log("❌ Ollama not detected! Please install Ollama from ollama.com")
            messagebox.showwarning("Ollama Missing", "Ollama is not installed on this system. Please download and install it from https://ollama.com before using Gemma Forge.")
        elif not is_ollama_running():
            early_log("⚠️ Ollama is installed but not running. Please start the Ollama application.")
            messagebox.showwarning("Ollama Not Running", "Ollama is installed but the server is not active. Please launch Ollama now.")
        else:
            version = get_ollama_version()
            early_log(f"✅ Ollama {version} detected and operational.")

        # Initialize HF Engine
        self.hf_engine = HuggingFaceEngine()

        # --- Tabbed Navigation ---
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=1, column=0, padx=20, pady=(20, 20), sticky="nsew")
        
        self.tab_hub = self.tabview.add("Hub Explorer")
        self.tab_forge = self.tabview.add("Forge")

        # Log Console MUST be initialized before calling self.log()
        self.log_text = ctk.CTkTextbox(self, font=("Courier New", 12), height=200, fg_color="#0f0f0f", text_color="#aaa")
        self.log_text.grid(row=2, column=0, padx=20, pady=10, sticky="ew")
        self.log_text.configure(state="disabled") 

        # Now we can safely call self.log for the system check summary
        self.log(f"System check complete. Ollama status: {'Running' if is_ollama_running() else 'Not Running'}")

        # Initialize views
        self.setup_hub_ui()
        self.setup_forge_ui()

        # Bind validation to entry changes
        self.src_entry.bind("<KeyRelease>", lambda e: self.validate_inputs())
        self.out_entry.bind("<KeyRelease>", lambda e: self.validate_inputs())
        self.name_entry.bind("<KeyRelease>", lambda e: self.validate_inputs())
        
        # Initial validation check
        self.validate_inputs()

    def setup_forge_ui(self):
        # Header
        self.header = ctk.CTkLabel(self.tab_forge, text="Forge Model", font=("Arial", 24, "bold"), text_color=config.get("ui.accent_color", "#3b8ed0"))
        self.header.pack(pady=20)

        # Main Container
        self.forge_frame = ctk.CTkScrollableFrame(self.tab_forge, fg_color="#252525")
        self.forge_frame.pack(padx=20, pady=10, fill="both", expand=True)
        self.forge_frame.grid_columnconfigure(1, weight=1)

        # --- Section 1: Source & Output ---
        self.create_section_label("1. Path Configuration", 0)
        
        self.src_label = ctk.CTkLabel(self.forge_frame, text="Source Model Folder:", font=("Arial", 13))
        self.src_label.grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.src_entry = ctk.CTkEntry(self.forge_frame, placeholder_text="Path to Safetensors / HF folder")
        self.src_entry.grid(row=1, column=1, padx=10, pady=5, sticky="ew")
        self.src_btn = ctk.CTkButton(self.forge_frame, text="Browse", command=self.browse_src, width=100, fg_color=config.get("ui.accent_color", "#3b8ed0"))
        self.src_btn.grid(row=1, column=2, padx=10, pady=5)
        self.src_hint = ctk.CTkLabel(self.forge_frame, text="The directory containing the model weights.", font=("Arial", 11), text_color="gray")
        self.src_hint.grid(row=2, column=1, padx=10, pady=(0, 10), sticky="w")

        self.out_label = ctk.CTkLabel(self.forge_frame, text="Output GGUF Path:", font=("Arial", 13))
        self.out_label.grid(row=3, column=0, padx=10, pady=5, sticky="w")
        self.out_entry = ctk.CTkEntry(self.forge_frame, placeholder_text="Where to save the .gguf file")
        self.out_entry.grid(row=3, column=1, padx=10, pady=5, sticky="ew")
        self.out_btn = ctk.CTkButton(self.forge_frame, text="Browse", command=self.browse_out, width=100, fg_color=config.get("ui.accent_color", "#3b8ed0"))
        self.out_btn.grid(row=3, column=2, padx=10, pady=5)
        self.out_hint = ctk.CTkLabel(self.forge_frame, text="Target file path ending in .gguf", font=("Arial", 11), text_color="gray")
        self.out_hint.grid(row=4, column=1, padx=10, pady=(0, 10), sticky="w")

        # IMPROVED VISUAL CUE: High visibility warning about the disabled button
        self.more_settings_lbl = ctk.CTkLabel(
            self.forge_frame, 
            text="⚠️ Note: The Forge button will remain grayed out until all settings below are configured ↓", 
            font=("Arial", 12, "bold"), 
            text_color="#ffcc00"
        )
        self.more_settings_lbl.grid(row=5, column=0, columnspan=3, pady=10)

        # --- Section 2: Quantization ---
        self.create_section_label("2. Model Quantization", 6)
        
        # ... (keep existing logic here) ...
        self.quant_label = ctk.CTkLabel(self.forge_frame, text="Quantization Level:", font=("Arial", 13))
        self.quant_label.grid(row=7, column=0, padx=10, pady=5, sticky="w")
        self.quant_var = ctk.StringVar(value="Q4_K_M")
        self.quant_menu = ctk.CTkOptionMenu(self.forge_frame, values=["FP16", "Q8_0", "Q4_K_M", "Q4_0", "Q2_K"], variable=self.quant_var, fg_color=config.get("ui.accent_color", "#3b8ed0"), button_color="#1f538d")
        self.quant_menu.grid(row=7, column=1, padx=10, pady=5, sticky="w")
        self.quant_hint = ctk.CTkLabel(self.forge_frame, text="Q4_K_M is recommended for most users (best balance).", font=("Arial", 11), text_color="gray")
        self.quant_hint.grid(row=8, column=1, padx=10, pady=(0, 10), sticky="w")

        # --- Section 3: Ollama Integration ---
        self.create_section_label("3. Ollama Import Settings", 9)
        
        self.name_label = ctk.CTkLabel(self.forge_frame, text="Ollama Model Name:", font=("Arial", 13))
        self.name_label.grid(row=10, column=0, padx=10, pady=5, sticky="w")
        self.name_entry = ctk.CTkEntry(self.forge_frame, placeholder_text="my-gemma-4-model")
        self.name_entry.grid(row=10, column=1, padx=10, pady=5, sticky="ew")
        self.name_hint = ctk.CTkLabel(self.forge_frame, text="This is the name you will use in 'ollama run <name>'", font=("Arial", 11), text_color="gray")
        self.name_hint.grid(row=11, column=1, padx=10, pady=(0, 10), sticky="w")

        # --- Section 4: Advanced Parameters (Dynamic Modelfile) ---
        self.create_section_label("4. Advanced Model Parameters", 12)

        # Temperature
        self.temp_label = ctk.CTkLabel(self.forge_frame, text="Temperature:", font=("Arial", 13))
        self.temp_label.grid(row=13, column=0, padx=10, pady=5, sticky="w")
        self.temp_var = ctk.DoubleVar(value=config.get("modelfile_defaults.temperature", 1.0))
        self.temp_slider = ctk.CTkSlider(self.forge_frame, from_=0.0, to=2.0, variable=self.temp_var, command=lambda v: self.snap_slider(v, self.temp_var))
        self.temp_slider.grid(row=13, column=1, padx=10, pady=5, sticky="ew")
        self.temp_val_lbl = ctk.CTkLabel(self.forge_frame, textvariable=self.temp_var, width=40)
        self.temp_val_lbl.grid(row=13, column=2, padx=10, pady=5)
        self.temp_hint = ctk.CTkLabel(self.forge_frame, text="Higher = more creative/random, Lower = more deterministic.", font=("Arial", 11), text_color="gray")
        self.temp_hint.grid(row=14, column=1, padx=10, pady=(0, 10), sticky="w")

        # Top-P
        self.top_p_label = ctk.CTkLabel(self.forge_frame, text="Top-P:", font=("Arial", 13))
        self.top_p_label.grid(row=15, column=0, padx=10, pady=5, sticky="w")
        self.top_p_var = ctk.DoubleVar(value=config.get("modelfile_defaults.top_p", 0.95))
        self.top_p_slider = ctk.CTkSlider(self.forge_frame, from_=0.0, to=1.0, variable=self.top_p_var, command=lambda v: self.snap_slider(v, self.top_p_var))
        self.top_p_slider.grid(row=15, column=1, padx=10, pady=5, sticky="ew")
        self.top_p_val_lbl = ctk.CTkLabel(self.forge_frame, textvariable=self.top_p_var, width=40)
        self.top_p_val_lbl.grid(row=15, column=2, padx=10, pady=5)
        self.top_p_hint = ctk.CTkLabel(self.forge_frame, text="Nucleus sampling: limits the model to a subset of tokens.", font=("Arial", 11), text_color="gray")
        self.top_p_hint.grid(row=16, column=1, padx=10, pady=(0, 10), sticky="w")

        # Top-K
        self.top_k_label = ctk.CTkLabel(self.forge_frame, text="Top-K:", font=("Arial", 13))
        self.top_k_label.grid(row=17, column=0, padx=10, pady=5, sticky="w")
        self.top_k_var = ctk.IntVar(value=config.get("modelfile_defaults.top_k", 64))
        self.top_k_slider = ctk.CTkSlider(self.forge_frame, from_=1, to=256, variable=self.top_k_var)
        self.top_k_slider.grid(row=17, column=1, padx=10, pady=5, sticky="ew")
        self.top_k_val_lbl = ctk.CTkLabel(self.forge_frame, textvariable=self.top_k_var, width=40)
        self.top_k_val_lbl.grid(row=17, column=2, padx=10, pady=5)
        self.top_k_hint = ctk.CTkLabel(self.forge_frame, text="Limits the most likely tokens to the top K.", font=("Arial", 11), text_color="gray")
        self.top_k_hint.grid(row=18, column=1, padx=10, pady=(0, 10), sticky="w")

        # Template Selection
        self.tpl_label = ctk.CTkLabel(self.forge_frame, text="Prompt Template:", font=("Arial", 13))
        self.tpl_label.grid(row=19, column=0, padx=10, pady=5, sticky="w")
        self.tpl_var = ctk.StringVar(value="gemma_thinking")
        self.tpl_menu = ctk.CTkOptionMenu(self.forge_frame, values=list(AppConfig.TEMPLATES.keys()), variable=self.tpl_var, fg_color=config.get("ui.accent_color", "#3b8ed0"), button_color="#1f538d")
        self.tpl_menu.grid(row=19, column=1, padx=10, pady=5, sticky="w")
        self.tpl_hint = ctk.CTkLabel(self.forge_frame, text="Choose the format the model expects for conversations.", font=("Arial", 11), text_color="gray")
        self.tpl_hint.grid(row=20, column=1, padx=10, pady=(0, 10), sticky="w")

        # System Prompt
        self.sys_label = ctk.CTkLabel(self.forge_frame, text="System Prompt:", font=("Arial", 13))
        self.sys_label.grid(row=21, column=0, padx=10, pady=5, sticky="nw")
        self.sys_entry = ctk.CTkTextbox(self.forge_frame, height=100, fg_color="#1a1a1a", text_color="#eee")
        self.sys_entry.grid(row=21, column=1, padx=10, pady=5, sticky="ew")
        self.sys_entry.insert("1.0", config.get("modelfile_defaults.system_prompt", "You are a helpful assistant."))
        self.sys_hint = ctk.CTkLabel(self.forge_frame, text="Defines the model's identity and behavior.", font=("Arial", 11), text_color="gray")
        self.sys_hint.grid(row=22, column=1, padx=10, pady=(0, 10), sticky="w")

        # Action Button
        self.run_btn = ctk.CTkButton(self.tab_forge, text="Forge Model", command=self.start_process, font=("Arial", 18, "bold"), height=60, fg_color=config.get("ui.accent_color", "#3b8ed0"), hover_color="#2a6b9d")
        self.run_btn.pack(pady=10)

        # New Feature: Chat Interface Trigger
        self.chat_trigger_var = ctk.BooleanVar(value=False)
        self.chat_check = ctk.CTkCheckBox(self.tab_forge, text="Create chat interface when complete", variable=self.chat_trigger_var, font=("Arial", 13), fg_color=config.get("ui.accent_color", "#3b8ed0"))
        self.chat_check.pack(pady=10)

        # Progress Bar
        self.progress_bar = ctk.CTkProgressBar(self.tab_forge, progress_color=config.get("ui.accent_color", "#3b8ed0"))
        self.progress_bar.pack(padx=20, pady=10, fill="x")
        self.progress_bar.set(0)

    def setup_hub_ui(self):
        self.hub_frame = ctk.CTkFrame(self.tab_hub, fg_color="#252525")
        self.hub_frame.pack(padx=20, pady=20, fill="both", expand=True)
        self.hub_frame.grid_columnconfigure(1, weight=1)

        # Search Section
        self.search_container = ctk.CTkFrame(self.hub_frame, fg_color="transparent")
        self.search_container.grid(row=0, column=0, columnspan=2, padx=10, pady=(20, 10), sticky="ew")
        self.search_container.grid_columnconfigure(0, weight=1)

        self.search_entry = ctk.CTkEntry(
            self.search_container, 
            placeholder_text="Search models (e.g. 'Gemma 4' or 'Llama 3')...",
            height=40,
            font=("Arial", 14)
        )
        self.search_entry.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        self.search_btn = ctk.CTkButton(
            self.search_container, 
            text="Search Hub", 
            command=self.perform_search,
            width=120,
            height=40,
            font=("Arial", 14, "bold"),
            fg_color=config.get("ui.accent_color", "#3b8ed0")
        )
        self.search_btn.grid(row=0, column=1, padx=10, pady=10)
        
        self.search_hint = ctk.CTkLabel(
            self.search_container, 
            text="Tip: Use specific model names or keywords to narrow down results.", 
            font=("Arial", 12), 
            text_color="gray"
        )
        self.search_hint.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="w")

        # --- Featured Model: Gemma 4 Fast-Track ---
        self.featured_frame = ctk.CTkFrame(self.hub_frame, fg_color="#333333", border_width=2, border_color=config.get("ui.accent_color", "#3b8ed0"))
        self.featured_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=10, sticky="ew")
        self.featured_frame.grid_columnconfigure(0, weight=1)

        self.featured_lbl = ctk.CTkLabel(
            self.featured_frame, 
            text="⚡ Recommended: Optimized for Local AI", 
            font=("Arial", 14, "bold"),
            text_color=config.get("ui.accent_color", "#3b8ed0")
        )
        self.featured_lbl.grid(row=0, column=0, padx=10, pady=(5, 0), sticky="w")
        
        self.featured_model_lbl = ctk.CTkLabel(
            self.featured_frame, 
            text="google/gemma-4-E2B-it", 
            font=("Courier New", 16, "bold")
        )
        self.featured_model_lbl.grid(row=1, column=0, padx=10, pady=5, sticky="w")
        
        self.featured_desc_lbl = ctk.CTkLabel(
            self.featured_frame, 
            text="Works on small and old devices.", 
            font=("Arial", 12, "italic"),
            text_color="gray"
        )
        self.featured_desc_lbl.grid(row=2, column=0, padx=10, pady=(0, 10), sticky="w")
        
        self.featured_btn = ctk.CTkButton(
            self.featured_frame, 
            text="Deploy Now", 
            width=120, 
            height=35,
            font=("Arial", 13, "bold"),
            fg_color=config.get("ui.accent_color", "#3b8ed0"),
            command=lambda: self.select_model_as_source({"model_id": "google/gemma-4-E2B-it", "display_name": "Gemma-4-E2B-it", "downloads": "Direct", "license": "Apache 2.0", "available_formats": ["safetensors"]})
        )
        self.featured_btn.grid(row=1, column=1, padx=10, pady=5, sticky="e")

        # Results Area
        self.results_list = ctk.CTkScrollableFrame(
            self.hub_frame, 
            label_text="Available Models on Hugging Face", 
            label_font=("Arial", 16, "bold"),
            fg_color="#1a1a1a"
        )
        self.results_list.grid(row=2, column=0, columnspan=2, padx=10, pady=10, sticky="nsew")
        self.hub_frame.grid_rowconfigure(2, weight=1)
        self.hub_frame.grid_columnconfigure(0, weight=1)

    def perform_search(self):
        query = self.search_entry.get()
        self.log(f"Searching HF Hub for: {query}...")
        
        # Clear previous results
        for child in self.results_list.winfo_children():
            child.destroy()

        def search_thread():
            results = self.hf_engine.search_models(query=query)
            self.after(0, lambda: self.update_results_ui(results))

        threading.Thread(target=search_thread).start()

    def update_results_ui(self, results):
        if not results:
            self.log("No models found matching the query.")
            return

        for model in results:
            frame = ctk.CTkFrame(self.results_list)
            frame.pack(fill="x", padx=5, pady=5)
            
            info_text = f"{model['display_name']} | Downloads: {model['downloads']}"
            # Add format tags
            formats = model.get('available_formats', [])
            format_tags = " ".join([f"[{f}]" for f in formats])
            
            lbl = ctk.CTkLabel(frame, text=f"{info_text} {format_tags}", font=("Arial", 12))
            lbl.pack(side="left", padx=10, pady=5)
            
            # Enable "Use as Source" for both raw weights and pre-existing GGUFs
            btn_text = "Use as Source"
            if "gguf" in formats and not ( "safetensors" in formats or "pytorch" in formats):
                btn_text = "Direct GGUF"
            
            btn = ctk.CTkButton(
                frame, 
                text=btn_text, 
                width=120, 
                state="normal",
                command=lambda m=model: self.select_model_as_source(m)
            )
            btn.pack(side="right", padx=10, pady=5)

    def select_model_as_source(self, model):
        model_id = model['model_id']
        self.log(f"Selected {model_id}. Starting download... (This may take several minutes)")
        
        # Visual feedback: Disable search button during download
        self.search_btn.configure(state="disabled", text="Downloading...")
        
        def download_thread():
            try:
                # Download to the Gemma Forge framework workspace.
                base_path = config.get("paths.models_root")
                os.makedirs(base_path, exist_ok=True)
                model_dir = os.path.join(base_path, model_id.replace("/", "_"))
                
                self.log(f"Downloading to: {model_dir}")
                
                download_args = {
                    "repo_id": model_id,
                    "local_dir": model_dir,
                    "max_workers": 8,
                }
                if self.hf_engine.token:
                    download_args["token"] = self.hf_engine.token
                snapshot_download(**download_args)
                
                self.after(0, lambda: self.finalize_model_selection(model_dir, model_id))
            except Exception as e:
                self.after(0, lambda: self.handle_download_error(e))

        threading.Thread(target=download_thread, daemon=True).start()

    def handle_download_error(self, e):
        self.log(f"❌ Download failed: {e}")
        self.search_btn.configure(state="normal", text="Search Hub")
        messagebox.showerror("Download Error", f"Failed to download model:\n{e}")

    def finalize_model_selection(self, path, model_id=None):
        # Reset search button
        self.search_btn.configure(state="normal", text="Search Hub")
        
        # Populate Source Entry
        self.src_entry.delete(0, tk.END)
        self.src_entry.insert(0, path)
        
        # AUTO-SUGGEST Output Path
        model_name = os.path.basename(path)
        suggested_out = os.path.join(config.get("paths.models_root"), f"{model_name}.gguf")
        self.out_entry.delete(0, tk.END)
        self.out_entry.insert(0, suggested_out)
        
        # --- Strategic Model Naming ---
        # If this is the featured Gemma 4 model, lock the name to 'gemma-4' for the chat interface
        if model_id == "google/gemma-4-E2B-it":
            self.name_entry.delete(0, tk.END)
            self.name_entry.insert(0, "gemma-4")
            self.name_entry.configure(state="disabled")
            self.log("⚡ Featured Model detected: Name locked to 'gemma-4' for immediate chat connectivity.")
        else:
            # For custom models, ensure the field is editable
            self.name_entry.configure(state="normal")
            # Suggested name based on folder
            if not self.name_entry.get():
                self.name_entry.delete(0, tk.END)
                self.name_entry.insert(0, model_name.replace("_", "-").lower())
        
        self.log(f"✅ Model downloaded successfully to: {path}")
        self.log(f"Suggested output: {suggested_out}")
        
        # Smoothly switch to Forge tab
        self.tabview.set("Forge")
        self.validate_inputs() 
        messagebox.showinfo("Success", "Model downloaded! We've switched you to the Forge tab and set the paths.")

    def create_section_label(self, text, row):
        lbl = ctk.CTkLabel(self.forge_frame, text=text, font=("Arial", 14, "bold"), text_color="gray")
        lbl.grid(row=row, column=0, columnspan=3, padx=10, pady=(20, 10), sticky="w")

    def browse_src(self):
        path = filedialog.askdirectory()
        if path:
            self.src_entry.delete(0, tk.END)
            self.src_entry.insert(0, path)
            self.validate_inputs()

    def browse_out(self):
        path = filedialog.asksaveasfilename(defaultextension=".gguf")
        if path:
            self.out_entry.delete(0, tk.END)
            self.out_entry.insert(0, path)
            self.validate_inputs()

    def log(self, message):
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)

    def snap_slider(self, value, var):
        """Rounds the slider value to one decimal place."""
        snapped = round(float(value), 1)
        var.set(snapped)
        self.validate_inputs()

    def validate_inputs(self):
        """Checks if all required fields are filled and valid."""
        src = self.src_entry.get()
        out = self.out_entry.get()
        name = self.name_entry.get()

        # Basic presence check
        is_valid = all([src, out, name])

        if is_valid:
            self.run_btn.configure(state="normal", text="Forge Model", fg_color=config.get("ui.color", "blue"))
        else:
            self.run_btn.configure(state="disabled", text="Fill Required Fields", fg_color="gray")
        
        return is_valid

    def start_process(self):
        if not self.validate_inputs():
            return

        self.run_btn.configure(state="disabled")
        # Enable text box for writing
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        
        thread = threading.Thread(target=self.run_conversion, daemon=True)
        thread.start()

    def run_conversion(self):
        try:
            src = self.src_entry.get()
            out = self.out_entry.get()
            quant = self.quant_var.get()
            model_name = self.name_entry.get()
            
            temp = self.temp_var.get()
            top_p = self.top_p_var.get()
            top_k = self.top_k_var.get()
            sys_prompt = self.sys_entry.get("1.0", tk.END).strip()
            template_key = self.tpl_var.get()
            template = AppConfig.TEMPLATES.get(template_key, AppConfig.TEMPLATES["default"])

            if not src or not out or not model_name:
                raise ValueError("Please fill in all required fields.")

            # Check if source is already GGUF
            is_already_gguf = False
            gguf_file = None
            if os.path.isdir(src):
                for f in os.listdir(src):
                    if f.endswith(".gguf"):
                        gguf_file = os.path.join(src, f)
                        is_already_gguf = True
                        break
            elif src.endswith(".gguf"):
                gguf_file = src
                is_already_gguf = True

            # Confirmation for overwrite
            if os.path.exists(out):
                if not messagebox.askyesno("Overwrite Warning", f"File already exists at {out}. Overwrite?"):
                    self.after(0, lambda: self.run_btn.configure(state="normal"))
                    return

            if is_already_gguf:
                self.log(f"✨ Detected pre-existing GGUF: {gguf_file}")
                self.log("Skipping conversion and quantization steps...")
                
                import shutil
                self.log(f"Copying GGUF to output path: {out}")
                shutil.copy2(gguf_file, out)
                self.after(0, lambda: self.progress_bar.set(0.6))
            else:
                self.after(0, lambda: self.progress_bar.set(0.1))
                self.log(f"[1/4] Converting {src} to GGUF (FP16)...")
                out_temp = out.replace(".gguf", "-f16.gguf")
                
                llama_cpp_root = config.get("paths.llama_cpp_root")
                self.execute_cmd(f"python {llama_cpp_root}/convert_hf_to_gguf.py {src} --outfile {out_temp}")
                self.after(0, lambda: self.progress_bar.set(0.3))

                if quant != "FP16":
                    self.log(f"[2/4] Quantizing to {quant}...")
                    llama_cpp_bin = config.get("paths.llama_cpp_bin")
                    self.execute_cmd(f"{llama_cpp_bin}/llama-quantize {out_temp} {out} {quant}")
                    os.remove(out_temp)
                    self.after(0, lambda: self.progress_bar.set(0.6))
                else:
                    self.log("[2/4] Skipping quantization (FP16 selected).")
                    os.rename(out_temp, out)
                    self.after(0, lambda: self.progress_bar.set(0.4))

            self.log(f"[3/4] Generating Dynamic Modelfile for {model_name}...")
            modelfile_content = f"FROM {os.path.abspath(out)}\n"
            modelfile_content += f"PARAMETER temperature {temp}\n"
            modelfile_content += f"PARAMETER top_p {top_p}\n"
            modelfile_content += f"PARAMETER top_k {top_k}\n"
            modelfile_content += f"SYSTEM \"{sys_prompt}\"\n"
            modelfile_content += f"TEMPLATE \"\"\"{template}\"\"\""
            
            with open("Modelfile", "w") as f:
                f.write(modelfile_content)
            self.after(0, lambda: self.progress_bar.set(0.8))

            self.log(f"[4/4] Importing into Ollama as '{model_name}'...")
            self.execute_cmd(f"ollama create {model_name} -f Modelfile")
            self.after(0, lambda: self.progress_bar.set(1.0))

            self.log("\n✅ Forge Process Completed Successfully!")
            messagebox.showinfo("Success", f"Model {model_name} is now available in Ollama!")

            if self.chat_trigger_var.get():
                self.log("🚀 Launching Intelligence Interface...")
                self.launch_chat_interface(model_name)

        except Exception as e:
            self.log(f"\n❌ Error: {str(e)}")
            messagebox.showerror("Error", str(e))
        finally:
            self.run_btn.configure(state="normal")
            self.after(0, lambda: self.progress_bar.set(0))

    def launch_chat_interface(self, model_name):
        """Starts the Forge Harness server and opens the browser interface."""
        self.log("Starting Forge Harness on port 5005...")
        
        def server_process():
            try:
                project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
                subprocess.Popen(
                    [sys.executable, "-m", "chat.server"],
                    cwd=project_root,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                
                # Give it a moment to initialize
                import time
                time.sleep(2)
                
                # Open the browser
                webbrowser.open("http://localhost:5005")
                self.log("✅ Intelligence Interface is now live at http://localhost:5005")
            except Exception as e:
                self.log(f"❌ Failed to launch chat interface: {e}")

        threading.Thread(target=server_process, daemon=True).start()

    def execute_cmd(self, cmd):
        self.log(f"Running: {cmd}")
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            self.log(line.strip())
        process.wait()
        if process.returncode != 0:
            raise RuntimeError(f"Command failed with exit code {process.returncode}")

def set_appearance_mode(mode):
    ctk.set_appearance_mode(mode)

def set_default_color_theme(theme):
    ctk.set_default_color_theme(theme)

if __name__ == "__main__":
    app = GGUFConverterApp()
    app.mainloop()
