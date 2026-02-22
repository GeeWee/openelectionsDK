# /// script
# dependencies = [
#   "requests==2.31.0",
#   "beautifulsoup4==4.12.2",
#   "python-dateutil==2.8.2"
# ]
# ///

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

def scrape_candidates():
    # Load official storkreds list from storkredse.json
    try:
        with open('storkredse.json', 'r', encoding='utf-8') as f:
            official_storkreds_list = json.load(f)
    except FileNotFoundError:
        print("Warning: storkredse.json not found, using fallback list")
        official_storkreds_list = [
            "Københavns Omegns", "København", "Nordsjælland", "Bornholm",
            "Sjælland", "Fyn", "Sydjylland", "Østjylland", "Vestjylland", "Nordjylland"
        ]
    except json.JSONDecodeError:
        print("Warning: storkredse.json is invalid, using fallback list")
        official_storkreds_list = [
            "Københavns Omegns", "København", "Nordsjælland", "Bornholm",
            "Sjælland", "Fyn", "Sydjylland", "Østjylland", "Vestjylland", "Nordjylland"
        ]
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
                # Extract storkreds from header
                header_text = element.get_text(strip=True)
                
                # Extract storkreds name from header
                # First check for Københavns Omegns Storkreds specifically
                if 'Københavns Omegn' in header_text:
                    current_storkreds = 'Københavns Omegn'
                else:
                    storkreds_match = re.search(r'(København|Nordsjælland|Vestsjælland|Syddanmark|Nordjylland|Østjylland|Vestjylland|Sjælland|Fyn|Bornholm)', header_text)
                    if storkreds_match:
                        current_storkreds = storkreds_match.group(1)
                    else:
                        # Fallback: look for any region name
                        storkreds_keywords = ['København', 'Nordsjælland', 'Vestsjælland', 'Syddanmark', 
                                            'Nordjylland', 'Østjylland', 'Vestjylland', 'Sjælland',
                                            'Fyn', 'Bornholm']
                        for keyword in storkreds_keywords:
                            if keyword in header_text:
                                current_storkreds = keyword
                                break
                
                print(f"Header: {header_text} -> Storkreds: {current_storkreds}")
            else:  # candidate
                candidate = {}
                
                # Extract email
                email_link = element.select_one('a[href^="mailto:"]')
                if email_link:
                    email = email_link['href'].replace('mailto:', '').strip()
                    candidate['email'] = email
                else:
                    candidate['email'] = ''
                
                # Extract name
                name = ''
                if candidate['email']:
                    container_text = element.get_text(' ', strip=True)
                    email_text_pos = container_text.find(candidate['email'])
                    if email_text_pos > 0:
                        potential_name = container_text[:email_text_pos].strip()
                        potential_name = ' '.join(potential_name.split())
                        name_parts = potential_name.split()
                        if len(name_parts) <= 4:  # Likely a name
                            name = potential_name
                
                candidate['name'] = name
                
                # Extract additional information
                additional_info = ''
                if candidate['email'] and email_text_pos > 0:
                    additional_info = container_text[email_text_pos + len(candidate['email']):].strip()
                    additional_info = ' '.join(additional_info.split())
                
                candidate['additional_info'] = additional_info
                candidate['storkreds'] = current_storkreds
                candidate['party'] = 'SF'
                
                candidates.append(candidate)
                print(f"Candidate: {name} - {candidate['email']} - {current_storkreds}")
        
        # Save results
        if candidates:
            if args.format == 'json':
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(candidates, f, ensure_ascii=False, indent=2)
            else:  # csv
                with open(output_file, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=['name', 'email', 'storkreds', 'additional_info', 'party'])
                    writer.writeheader()
                    writer.writerows(candidates)
            
            print(f"\nSuccessfully saved {len(candidates)} candidates to {output_file}")
            
            # Statistics
            emails_found = sum(1 for c in candidates if c['email'])
            names_found = sum(1 for c in candidates if c['name'])
            storkreds_found = sum(1 for c in candidates if c['storkreds'])
            
            print(f"Statistics:")
            print(f"  Candidates with emails: {emails_found}/{len(candidates)}")
            print(f"  Candidates with names: {names_found}/{len(candidates)}")
            print(f"  Candidates with storkreds: {storkreds_found}/{len(candidates)}")
            
            # Storkreds distribution
            storkreds_distribution = {}
            for candidate in candidates:
                if candidate['storkreds']:
                    storkreds_distribution[candidate['storkreds']] = storkreds_distribution.get(candidate['storkreds'], 0) + 1
            
            print(f"\nStorkreds distribution:")
            for storkreds, count in sorted(storkreds_distribution.items()):
                print(f"  {storkreds}: {count} candidates")
            
            # Check if all candidates have storkreds
            candidates_without_storkreds = sum(1 for c in candidates if not c['storkreds'])
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