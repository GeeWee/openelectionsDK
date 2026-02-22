

import os
import sys
import argparse
import json
import csv
import re
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from models import Candidate
from utils import find_most_similar_storkreds

def scrape_candidates():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Scrape candidate data from SF website')
    parser.add_argument('--format', choices=['json', 'csv'], default='json', 
                       help='Output format (json or csv)')
    parser.add_argument('--output', default='output/candidates',
                       help='Output file path (without extension)')
    args = parser.parse_args()

    # Create output directory if it doesn't exist
    output_dir = os.path.dirname(args.output)
    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    output_file = f"{args.output}.{args.format}"
    
    # Configure headers
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    base_url = "https://sf.dk/dine-politikere/folketingskandidater-2026/"
    candidates = []
    
    try:
        print(f"Fetching data from {base_url}")
        response = requests.get(base_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        print(f"Page loaded successfully. Response size: {len(response.text)} characters")
        
        # Find all politiker_liste elements
        politiker_liste_elements = soup.select('.politiker_liste')
        print(f"Found {len(politiker_liste_elements)} politiker_liste elements")
        
        if politiker_liste_elements:
            # Process each list separately
            for liste_index, liste_element in enumerate(politiker_liste_elements):
                print(f"\nProcessing list {liste_index + 1}")
                
                # Find the first header in this list as the storkreds
                first_header = liste_element.select_one('div.col-xs-12.politiker_overskrift.h1.text-left, .politiker_overskrift, h1, h2, h3')
                if first_header:
                    header_text = first_header.get_text(strip=True)
                    current_storkreds = find_most_similar_storkreds(header_text)
                    print(f"List header: {header_text} -> Storkreds: {current_storkreds}")
                else:
                    current_storkreds = None
                    print(f"No header found in list {liste_index + 1}")
                
                # Find all politicians in this list
                politicians_in_list = liste_element.select('.politiker')
                print(f"Found {len(politicians_in_list)} politicians in this list")
                
                # Process each politician in this list
                for politician in politicians_in_list:
                    # Extract email
                    email = None
                    email_link = politician.select_one('a[href^="mailto:"]')
                    if email_link:
                        email = email_link['href'].replace('mailto:', '').strip()
                    
                    # Extract name
                    name = ''
                    container_text = politician.get_text(' ', strip=True)
                    
                    if email:
                        email_text_pos = container_text.find(email)
                        if email_text_pos > 0:
                            potential_name = container_text[:email_text_pos].strip()
                            potential_name = ' '.join(potential_name.split())
                            name_parts = potential_name.split()
                            if len(name_parts) <= 4:  # Likely a name
                                name = potential_name
                    
                    # Extract additional information
                    additional_info = ''
                    if email and email_text_pos > 0:
                        additional_info = container_text[email_text_pos + len(email):].strip()
                        additional_info = ' '.join(additional_info.split())
                    
                    # Create Candidate object using Pydantic model
                    try:
                        candidate = Candidate(
                            name=name,
                            party='SF',
                            email=email if email else None,
                            storkreds=current_storkreds if current_storkreds else None,
                            additional_info=additional_info if additional_info else None
                        )
                        candidates.append(candidate)
                        print(f"Candidate: {candidate.name} - {candidate.email} - {candidate.storkreds}")
                    except Exception as e:
                        print(f"Error creating candidate: {e}")
                        print(f"Candidate data: name='{name}', email='{email}', storkreds='{current_storkreds}'")
        else:
            # Fallback to original logic if no politiker_liste elements found
            print("No politiker_liste elements found, falling back to original logic")
            
            # Find all storkreds headers
            storkreds_headers = soup.select('div.col-xs-12.politiker_overskrift.h1.text-left')
            print(f"Found {len(storkreds_headers)} storkreds headers")
            
            # Find all candidate containers
            candidate_containers = soup.select('div.politiker')
            print(f"Found {len(candidate_containers)} candidate containers")
            
            # Create a list of all elements in order: headers and candidates
            all_elements = []
            
            # Add headers to the list
            for header in storkreds_headers:
                all_elements.append(('header', header))
            
            # Add candidates to the list
            for candidate in candidate_containers:
                all_elements.append(('candidate', candidate))
            
            # Sort all elements by their position in the document
            all_elements.sort(key=lambda x: x[1].sourceline if hasattr(x[1], 'sourceline') else 0)
            
            # Now process in order to assign storkreds
            current_storkreds = ""
            
            for element_type, element in all_elements:
                if element_type == 'header':
                    # Extract storkreds from header using the utils function
                    header_text = element.get_text(strip=True)
                    current_storkreds = find_most_similar_storkreds(header_text)
                    
                    print(f"Header: {header_text} -> Storkreds: {current_storkreds}")
                else:  # candidate
                    # Extract email
                    email = None
                    email_link = element.select_one('a[href^="mailto:"]')
                    if email_link:
                        email = email_link['href'].replace('mailto:', '').strip()
                    
                    # Extract name
                    name = ''
                    container_text = element.get_text(' ', strip=True)
                    
                    if email:
                        email_text_pos = container_text.find(email)
                        if email_text_pos > 0:
                            potential_name = container_text[:email_text_pos].strip()
                            potential_name = ' '.join(potential_name.split())
                            name_parts = potential_name.split()
                            if len(name_parts) <= 4:  # Likely a name
                                name = potential_name
                    
                    # Extract additional information
                    additional_info = ''
                    if email and email_text_pos > 0:
                        additional_info = container_text[email_text_pos + len(email):].strip()
                        additional_info = ' '.join(additional_info.split())
                    
                    # Create Candidate object using Pydantic model
                    try:
                        candidate = Candidate(
                            name=name,
                            party='SF',
                            email=email if email else None,
                            storkreds=current_storkreds if current_storkreds else None,
                            additional_info=additional_info if additional_info else None
                        )
                        candidates.append(candidate)
                        print(f"Candidate: {candidate.name} - {candidate.email} - {candidate.storkreds}")
                    except Exception as e:
                        print(f"Error creating candidate: {e}")
                        print(f"Candidate data: name='{name}', email='{email}', storkreds='{current_storkreds}'")
        
        # Save results
        if candidates:
            if args.format == 'json':
                # Convert Pydantic models to dictionaries for JSON serialization
                candidates_dict = [candidate.model_dump() for candidate in candidates]
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(candidates_dict, f, ensure_ascii=False, indent=2)
            else:  # csv
                with open(output_file, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=['name', 'email', 'storkreds', 'additional_info', 'party'])
                    writer.writeheader()
                    # Convert Pydantic models to dictionaries for CSV writing
                    candidates_dict = [candidate.model_dump() for candidate in candidates]
                    writer.writerows(candidates_dict)
            
            print(f"\nSuccessfully saved {len(candidates)} candidates to {output_file}")
            
            # Statistics
            emails_found = sum(1 for c in candidates if c.email)
            names_found = sum(1 for c in candidates if c.name)
            storkreds_found = sum(1 for c in candidates if c.storkreds)
            
            print(f"Statistics:")
            print(f"  Candidates with emails: {emails_found}/{len(candidates)}")
            print(f"  Candidates with names: {names_found}/{len(candidates)}")
            print(f"  Candidates with storkreds: {storkreds_found}/{len(candidates)}")
            
            # Storkreds distribution
            storkreds_distribution = {}
            for candidate in candidates:
                if candidate.storkreds:
                    storkreds_distribution[candidate.storkreds] = storkreds_distribution.get(candidate.storkreds, 0) + 1
            
            print(f"\nStorkreds distribution:")
            for storkreds, count in sorted(storkreds_distribution.items()):
                print(f"  {storkreds}: {count} candidates")
            
            # Check if all candidates have storkreds
            candidates_without_storkreds = sum(1 for c in candidates if not c.storkreds)
            if candidates_without_storkreds > 0:
                print(f"\nWarning: {candidates_without_storkreds} candidates without storkreds")
            else:
                print(f"\nAll candidates have storkreds assigned!")
            
            return 0
        else:
            print("No candidates found.")
            return 1
            
    except requests.RequestException as e:
        print(f"Error fetching the website: {e}")
        return 1
    except Exception as e:
        print(f"Error processing data: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(scrape_candidates())