# /// script
# dependencies = [
#   "python-Levenshtein==0.25.0",
#   "pytest==8.3.2"
# ]
# ///

import json
import Levenshtein

def find_most_similar_storkreds(input_string):
    """
    Find the most similar storkreds name to the input string using Levenshtein distance.
    
    Uses a combination of Levenshtein distance and substring matching for better accuracy.
    Returns None if the input is too ambiguous (matches multiple storkreds equally well).

    Args:
        input_string (str): The string to compare against storkreds names

    Returns:
        str: The most similar storkreds name from storkredse.json, or None if ambiguous
    """
    with open('storkredse.json', 'r', encoding='utf-8') as f:
        storkreds_list = json.load(f)

    if not input_string:
        return None

    # First pass: calculate scores for all storkreds
    scores = []
    for storkreds in storkreds_list:
        # Calculate Levenshtein distance
        distance = Levenshtein.distance(input_string, storkreds)
        normalized_distance = distance / max(len(input_string), len(storkreds))
        
        # Add bonus for exact substring matches
        substring_bonus = 0
        if input_string.lower() in storkreds.lower():
            # Significant bonus if input is a substring of storkreds
            substring_bonus = -0.3  # Large negative bonus
        elif storkreds.lower() in input_string.lower():
            # Smaller bonus if storkreds is a substring of input
            substring_bonus = -0.1
        
        # Calculate combined score
        score = normalized_distance + substring_bonus
        scores.append((storkreds, score))

    # Find the best score
    best_score = min(score for _, score in scores)
    
    # Find all storkreds with the best score
    best_matches = [storkreds for storkreds, score in scores if score == best_score]
    
    # If there's a tie (ambiguous), return None
    if len(best_matches) > 1:
        return None
    
    # Otherwise return the single best match
    return best_matches[0] if best_matches else None

def get_storkreds_similarity_score(input_string):
    """
    Get similarity scores for all storkreds names compared to input string.

    Args:
        input_string (str): The string to compare against storkreds names

    Returns:
        dict: Dictionary with storkreds names as keys and similarity scores as values
    """
    with open('storkredse.json', 'r', encoding='utf-8') as f:
        storkreds_list = json.load(f)

    similarity_scores = {}

    for storkreds in storkreds_list:
        distance = Levenshtein.distance(input_string, storkreds)
        similarity_scores[storkreds] = distance / max(len(input_string), len(storkreds), 1)

    return similarity_scores

# Test cases
def test_exact_matches():
    """Test that exact matches return the correct storkreds"""
    assert find_most_similar_storkreds("København") == "København"
    assert find_most_similar_storkreds("Fyn") == "Fyn"
    assert find_most_similar_storkreds("Nordjylland") == "Nordjylland"

def test_typo_correction():
    """Test that common typos are corrected properly"""
    assert find_most_similar_storkreds("Københavns Omegns") == "Københavns Omegns"
    assert find_most_similar_storkreds("Nordjland") == "Nordjylland"
    assert find_most_similar_storkreds("Sjæland") == "Sjælland"

def test_partial_matches():
    """Test that partial strings find the right match"""
    assert find_most_similar_storkreds("København") == "København"
    assert find_most_similar_storkreds("Nordjyll") == "Nordjylland"  # Should match the most specific
    assert find_most_similar_storkreds("Bornholm") == "Bornholm"
    assert find_most_similar_storkreds("Jylland") is None  # Ambiguous - could match multiple Jylland regions

def test_empty_input():
    """Test that empty input returns None"""
    assert find_most_similar_storkreds("") is None
    assert find_most_similar_storkreds(None) is None

def test_similarity_scores():
    """Test that similarity scores work correctly"""
    scores = get_storkreds_similarity_score("København")
    assert "København" in scores
    assert scores["København"] == 0.0  # Exact match should have 0 distance

    scores = get_storkreds_similarity_score("Københavns Omegns")
    assert scores["Københavns Omegns"] == 0.0

def test_case_sensitivity():
    """Test that matching is case sensitive (as it should be for Danish names)"""
    # These should not match exactly due to case differences
    result = find_most_similar_storkreds("københavn")
    assert result == "København"  # Should still find it as closest match


def test_ambiguous_cases():
    """Test that ambiguous inputs return None"""
    # "Jylland" could match any of the Jylland regions
    assert find_most_similar_storkreds("Jylland") is None
    
    # "Sjælland" is exact, but "Sjæ" could be ambiguous
    result = find_most_similar_storkreds("Sjæ")
    # This should either find Sjælland or return None if ambiguous
    assert result in ["Sjælland", None]

if __name__ == "__main__":
    import pytest
    import sys

    # Run tests
    exit_code = pytest.main([__file__, "-v"])
    sys.exit(exit_code)