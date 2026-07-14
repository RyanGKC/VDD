import argparse
import sys

def shorten_log(input_path, output_path):
    with open(input_path, 'r', encoding='utf-8') as infile, \
         open(output_path, 'w', encoding='utf-8') as outfile:
        
        current_line = None
        count = 0
        
        for line in infile:
            if current_line is None:
                current_line = line
                count = 1
            elif line == current_line:
                count += 1
            else:
                write_line(outfile, current_line, count)
                current_line = line
                count = 1
                
        # Write the final buffered line
        if current_line is not None:
            write_line(outfile, current_line, count)
            
def write_line(outfile, line, count):
    if count > 1:
        # Strip the trailing newline, add the count, and re-add the newline
        line_clean = line.rstrip('\r\n')
        outfile.write(f"{line_clean} ({count} times)\n")
    else:
        outfile.write(line)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Shorten a log file by collapsing consecutive identical lines.")
    parser.add_argument("input_file", help="Path to the input log file")
    parser.add_argument("output_file", help="Path to save the shortened log file")
    args = parser.parse_args()
    
    try:
        shorten_log(args.input_file, args.output_file)
        print(f"Successfully shortened logs and saved to {args.output_file}")
    except Exception as e:
        print(f"Error processing log file: {e}")
        sys.exit(1)
