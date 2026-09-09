import logging
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from gis_pipeline import PipelineOrchestrator

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class GISApp:
    def __init__(self, root):
        self.root = root
        self.root.title("NYS GIS Reference Marker Lookup")
        self.orchestrator = PipelineOrchestrator()
        self.filtered_suggestions = []

        # UI Elements
        self.root.geometry("640x480")
        self.root.resizable(False, False)

        # Title
        tk.Label(root, text="Search for Locations or Enter Coordinates", font=("Arial", 12, "bold")).pack(pady=5)

        search_frame = tk.Frame(root)
        search_frame.pack(pady=5, padx=10, fill=tk.X)
        
        tk.Label(search_frame, text="Address/Coords:").pack(side=tk.LEFT, padx=5)
        self.address_entry = tk.Entry(search_frame)
        self.address_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.address_entry.bind('<Return>', lambda event: self.start_search())
        self.address_entry.focus_set() # Set initial focus
        
        self.search_button = tk.Button(search_frame, text="Search", command=self.start_search)
        self.search_button.pack(side=tk.LEFT, padx=5)
        
        tk.Label(root, text="Select Suggestion:").pack(pady=(10, 0), padx=10, anchor=tk.W)
        self.suggestion_listbox = tk.Listbox(root, height=5)
        self.suggestion_listbox.pack(pady=5, padx=10, fill=tk.X)
        self.suggestion_listbox.bind('<<ListboxSelect>>', self.on_select)
        
        tk.Label(root, text="Reference Marker Details:").pack(pady=(10, 0), padx=10, anchor=tk.W)
        # Treeview for table display
        self.tree = ttk.Treeview(root, show="headings")
        self.tree.pack(pady=5, padx=10, fill=tk.BOTH, expand=True)

    def start_search(self):
        address = self.address_entry.get()
        if not address:
            messagebox.showwarning("Input Error", "Please enter an address.")
            return
        
        # Check for coordinates
        coord_point_sr = self.orchestrator.parse_coordinate_query(address)
        if coord_point_sr:
            logger.debug(f"Detected coordinates: {coord_point_sr}")
            self.search_button.config(state=tk.DISABLED)
            self.suggestion_listbox.delete(0, tk.END)
            self.suggestion_listbox.insert(tk.END, "Searching coordinates...")
            threading.Thread(target=self.search_coordinates, args=(coord_point_sr,), daemon=True).start()
            return

        logger.debug(f"Starting search for: {address}")
        self.search_button.config(state=tk.DISABLED)
        self.suggestion_listbox.delete(0, tk.END)
        self.suggestion_listbox.insert(tk.END, "Searching...")
        
        threading.Thread(target=self.search, args=(address,), daemon=True).start()

    def search_coordinates(self, coord_point_sr):
        point, sr = coord_point_sr
        # Default radius 0.5 miles for now
        results = self.orchestrator.marker_service.identify(point, sr, radius_miles=0.5)
        logger.debug(f"Identify result for coordinates: {results}")
        
        # Store as single item
        self.filtered_suggestions = [{'suggestion': {'text': 'Coordinates'}, 'results': results, 'point': point}]
        
        # Update UI in main thread
        self.root.after(0, self.update_suggestions_ui)

    def search(self, address):
        suggestions = self.orchestrator.geocoder.suggest(address)
        logger.debug(f"Suggestions received: {len(suggestions)}")
        self.filtered_suggestions = []
        
        # Filter suggestions by successful identification
        for s in suggestions:
            candidate = self.orchestrator.geocoder.geocode(s['magicKey'])
            if candidate:
                point = candidate['location']
                sr = candidate.get('spatialReference', {}).get('wkid')
                # Use default radius 0.5 miles for address searches
                results = self.orchestrator.marker_service.identify(point, sr, radius_miles=0.5)
                logger.debug(f"Identify result for {s['text']}: {results}")
                if results.get('results'):
                    self.filtered_suggestions.append({'suggestion': s, 'results': results, 'point': point})
        
        # Update UI in main thread
        self.root.after(0, self.update_suggestions_ui)

    def update_suggestions_ui(self):
        self.suggestion_listbox.delete(0, tk.END)
        for fs in self.filtered_suggestions:
            self.suggestion_listbox.insert(tk.END, fs['suggestion']['text'])
        self.search_button.config(state=tk.NORMAL)
        logger.debug("Suggestions UI updated")

    def on_select(self, event):
        selection = self.suggestion_listbox.curselection()
        if not selection:
            return
        
        index = selection[0]
        fs = self.filtered_suggestions[index]
        logger.debug(f"Selected suggestion: {fs['suggestion']['text']}")
        
        # Get location from stored point
        point = fs['point']
        x = point.get('x')
        y = point.get('y')
        # Ensure we have the correct SR for the point
        # For address suggestions, they usually return projected coords
        # If the point object doesn't have SR, default to 26918
        sr = point.get('spatialReference', {}).get('wkid', 26918)
        
        results = fs['results'].get('results', [])
        if not results:
            return

        # Deduplicate based on OBJECTID
        unique_results = {}
        for r in results:
            attrs = r.get('attributes', {})
            obj_id = attrs.get('OBJECTID')
            if obj_id not in unique_results:
                unique_results[obj_id] = attrs
        
        attributes_list = list(unique_results.values())
        
        # Fields to filter out as they are always null
        fields_to_ignore = ['reverse overlap feature', 'continuity code', 'route sequence number']

        # Filter out ignored fields and log attributes for analysis
        for attrs in attributes_list:
            logger.debug(f"Attribute fields: {list(attrs.keys())}")
            for field in fields_to_ignore:
                attrs.pop(field, None)

        # Determine labels based on SR
        x_label, y_label = ("Easting", "Northing") if sr == 26918 else ("Longitude", "Latitude")
        
        # Dynamically determine columns based on attribute keys + coords
        all_keys = set()
        for attrs in attributes_list:
            all_keys.update(attrs.keys())
        all_keys.update([x_label, y_label])
        
        columns = sorted(list(all_keys))
        
        # Clear previous results and configure columns
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = columns
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100)
            
        # Insert new results with coords added
        for attrs in attributes_list:
            row_data = attrs.copy()
            row_data.update({x_label: x, y_label: y})
            values = tuple(row_data.get(col, "") for col in columns)
            self.tree.insert("", tk.END, values=values)
        logger.debug(f"Treeview updated with {len(attributes_list)} unique attributes and {x_label}/{y_label}: {x}, {y}")

if __name__ == "__main__":
    root = tk.Tk()
    app = GISApp(root)
    root.mainloop()
