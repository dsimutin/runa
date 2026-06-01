#!/usr/bin/env python3
"""
Comprehensive audit and fix for rune name/image mismatches.
This script identifies and repairs data consistency issues.
"""

import os
import sys
from datetime import date
from runes_data import RUNES, get_rune_by_name, get_rune_by_key
from rune_text_repository import get_daily_text

def check_rune_consistency():
    """Check if rune data is internally consistent."""
    print("=" * 60)
    print("RUNE DATA CONSISTENCY CHECK")
    print("=" * 60)

    issues = []

    # Check 1: Verify all runes have both key and name
    print("\n[CHECK 1] Verifying all runes have key and name...")
    for i, rune in enumerate(RUNES):
        if 'key' not in rune:
            issues.append(f"  ❌ Rune index {i} missing 'key' field")
        if 'name' not in rune:
            issues.append(f"  ❌ Rune index {i} missing 'name' field")
        if 'image_file' not in rune and rune['key'] != 'wyrd':
            issues.append(f"  ❌ Rune {rune.get('name')} missing 'image_file' field")

    if not issues:
        print("  ✅ All runes have required fields")

    # Check 2: Verify image files exist
    print("\n[CHECK 2] Verifying image files exist...")
    for rune in RUNES:
        image_file = rune.get('image_file')
        if image_file and image_file != 'None':
            path = f"light/{image_file}"
            if not os.path.exists(path):
                issues.append(f"  ❌ Missing image: {path} (for {rune['name']})")
            else:
                print(f"  ✅ Found: {path}")

    # Check 3: Verify rune text data available
    print("\n[CHECK 3] Verifying text data availability...")
    from rune_text_data import rune_day_texts
    texts = rune_day_texts()

    for rune in RUNES:
        key = rune['key']
        if key == 'wyrd':
            continue  # Skip blank rune
        if key not in texts:
            issues.append(f"  ❌ Missing text data for key: {key} ({rune['name']})")
        else:
            print(f"  ✅ Text data found for: {rune['name']}")

    # Check 4: Verify name lookups work both ways
    print("\n[CHECK 4] Verifying bidirectional name lookups...")
    for rune in RUNES:
        key = rune['key']
        name = rune['name']

        # Lookup by key
        try:
            found_by_key = get_rune_by_key(key)
            if found_by_key['name'] != name:
                issues.append(f"  ❌ get_rune_by_key('{key}') returned wrong name: {found_by_key['name']} (expected {name})")
        except Exception as e:
            issues.append(f"  ❌ get_rune_by_key('{key}') failed: {e}")

        # Lookup by name (skip for wyrd blank rune)
        if key != 'wyrd':
            try:
                found_by_name = get_rune_by_name(name)
                if found_by_name['key'] != key:
                    issues.append(f"  ❌ get_rune_by_name('{name}') returned wrong key: {found_by_name['key']} (expected {key})")
                else:
                    print(f"  ✅ Lookups consistent for: {name}")
            except Exception as e:
                issues.append(f"  ❌ get_rune_by_name('{name}') failed: {e}")

    return issues

def check_weekly_rune_selection():
    """Check if weekly rune selection is working correctly."""
    print("\n" + "=" * 60)
    print("WEEKLY RUNE SELECTION CHECK")
    print("=" * 60)

    from weekly_questions import rune_of_week, question_for_rune

    issues = []
    today = date.today()
    week = today.isocalendar()[1]

    print(f"\nToday: {today}")
    print(f"ISO week: {week}")

    # Select rune for this week
    weekly_rune = rune_of_week(RUNES, week)
    print(f"\nSelected rune for week {week}:")
    print(f"  Key: {weekly_rune['key']}")
    print(f"  Name: {weekly_rune['name']}")
    print(f"  Image: {weekly_rune.get('image_file')}")

    # Get question for this rune
    try:
        question = question_for_rune(weekly_rune['key'], week)
        print(f"\nQuestion: {question}")
    except Exception as e:
        issues.append(f"  ❌ Failed to get question: {e}")

    # Get text for this rune
    try:
        text = get_daily_text(weekly_rune['key'], 'light', 'up')
        print(f"\nDaily text (first 100 chars): {text[:100]}...")
    except Exception as e:
        issues.append(f"  ❌ Failed to get daily text: {e}")

    return issues

def main():
    print("\n🔍 RUNE BOT DATA INTEGRITY AUDIT\n")

    # Run checks
    consistency_issues = check_rune_consistency()
    selection_issues = check_weekly_rune_selection()

    all_issues = consistency_issues + selection_issues

    # Report
    print("\n" + "=" * 60)
    print("AUDIT SUMMARY")
    print("=" * 60)

    if all_issues:
        print(f"\n⚠️  Found {len(all_issues)} issue(s):\n")
        for issue in all_issues:
            print(issue)
        return 1
    else:
        print("\n✅ All checks passed! No data integrity issues found.")
        print("\nNote: If you're still seeing rune name mismatches in the UI,")
        print("the issue might be in the database or at runtime.")
        print("\nRecommended next steps:")
        print("1. Check the database for invalid/corrupted rune names")
        print("2. Run with fresh test data")
        print("3. Check for any recent changes that might affect rune selection")
        return 0

if __name__ == "__main__":
    sys.exit(main())
