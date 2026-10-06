import os
import pandas as pd

# Define the input and output paths
input_folder = 'media/L2_approved'          # Change accordingly
output_file = 'media/ishita/ishita.csv'    # Change accordingly
script_dir = os.path.dirname(os.path.abspath(__file__))
media_dir = os.path.join(script_dir, "media")
# Supported file extensions
supported_extensions = ['.csv', '.xls', '.xlsx']

# Initialize a list to collect DataFrames
all_data = []
c=0
# Iterate through files in the folder
for filename in os.listdir(input_folder):
    file_path = os.path.join(input_folder, filename)
    ext = os.path.splitext(filename)[1].lower()

    if ext in supported_extensions:
        try:
            if ext == '.csv':
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path)
            # df['SourceFile'] = filename  # Optional: Track origin
            all_data.append(df)
            c=c+1
        except Exception as e:
            print(f"Error reading {filename}: {e}")

# Combine all DataFrames
if all_data:
    combined_df = pd.concat(all_data, ignore_index=True)
    # combined_df.drop_duplicates(inplace=True)  # Remove duplicate rows
    combined_df.to_csv(output_file, index=False)
    combined = os.path.abspath(output_file)
    print(f"Combined file saved to: {output_file}")
    print(c)
else:
    print("No valid files found in the directory.")
