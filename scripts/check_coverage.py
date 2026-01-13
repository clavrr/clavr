#!/usr/bin/env python3
"""
Test Coverage Analysis and Reporting
Analyzes test coverage and generates detailed reports
"""
import os
import sys
import subprocess
import json
from pathlib import Path

def run_coverage():
    """Run tests with coverage"""
    print("=" * 80)
    print("Running tests with coverage...")
    print("=" * 80)
    
    # Run pytest with coverage
    result = subprocess.run(
        [
            "pytest",
            "--cov=src",
            "--cov=api",
            "--cov-report=html",
            "--cov-report=term",
            "--cov-report=json",
            "-v"
        ],
        capture_output=True,
        text=True
    )
    
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    
    return result.returncode == 0


def analyze_coverage():
    """Analyze coverage report"""
    coverage_file = Path("coverage.json")
    
    if not coverage_file.exists():
        print("❌ Coverage report not found")
        return None
    
    with open(coverage_file) as f:
        coverage_data = json.load(f)
    
    total_coverage = coverage_data.get("totals", {}).get("percent_covered", 0)
    
    print("\n" + "=" * 80)
    print("COVERAGE ANALYSIS")
    print("=" * 80)
    print(f"\n📊 Total Coverage: {total_coverage:.2f}%\n")
    
    # Files by coverage
    files = coverage_data.get("files", {})
    
    # Sort by coverage percentage
    file_coverage = []
    for filepath, data in files.items():
        summary = data.get("summary", {})
        percent = summary.get("percent_covered", 0)
        file_coverage.append((filepath, percent, summary))
    
    file_coverage.sort(key=lambda x: x[1])
    
    # Low coverage files
    print("📉 Files with Low Coverage (<50%):")
    low_coverage_found = False
    for filepath, percent, summary in file_coverage:
        if percent < 50:
            low_coverage_found = True
            missing = summary.get("missing_lines", 0)
            print(f"  {percent:5.1f}% - {filepath} ({missing} lines missing)")
    
    if not low_coverage_found:
        print("  ✅ No files with coverage below 50%")
    
    print("\n📈 Files with High Coverage (>80%):")
    high_coverage_found = False
    for filepath, percent, summary in file_coverage:
        if percent > 80:
            high_coverage_found = True
            print(f"  {percent:5.1f}% - {filepath}")
    
    if not high_coverage_found:
        print("  ⚠️  No files with coverage above 80%")
    
    # Coverage goals
    print("\n🎯 Coverage Goals:")
    
    goals = [
        (40, "🟡 Minimum"),
        (60, "🟢 Good"),
        (80, "🌟 Excellent"),
        (90, "💎 Outstanding")
    ]
    
    for threshold, label in goals:
        if total_coverage >= threshold:
            status = "✅ ACHIEVED"
        else:
            status = f"❌ Need {threshold - total_coverage:.1f}% more"
        print(f"  {label:20s} ({threshold}%): {status}")
    
    return total_coverage


def generate_coverage_badge():
    """Generate coverage badge data"""
    coverage_file = Path("coverage.json")
    
    if not coverage_file.exists():
        return
    
    with open(coverage_file) as f:
        coverage_data = json.load(f)
    
    total_coverage = coverage_data.get("totals", {}).get("percent_covered", 0)
    
    # Determine color
    if total_coverage >= 80:
        color = "brightgreen"
    elif total_coverage >= 60:
        color = "green"
    elif total_coverage >= 40:
        color = "yellow"
    else:
        color = "red"
    
    badge_data = {
        "schemaVersion": 1,
        "label": "coverage",
        "message": f"{total_coverage:.1f}%",
        "color": color
    }
    
    with open(".coverage-badge.json", "w") as f:
        json.dump(badge_data, f, indent=2)
    
    print(f"\n✅ Coverage badge generated: {total_coverage:.1f}% ({color})")


def identify_missing_tests():
    """Identify files that need more tests"""
    print("\n" + "=" * 80)
    print("MISSING TESTS ANALYSIS")
    print("=" * 80)
    
    # Look for Python files in src/ and api/ that might not have tests
    src_files = list(Path("src").rglob("*.py"))
    api_files = list(Path("api").rglob("*.py"))
    all_files = src_files + api_files
    
    # Exclude __init__.py and __pycache__
    all_files = [
        f for f in all_files 
        if f.name != "__init__.py" and "__pycache__" not in str(f)
    ]
    
    print(f"\n📁 Total source files: {len(all_files)}")
    
    # Check which files have corresponding tests
    test_files = list(Path("tests").rglob("test_*.py"))
    print(f"🧪 Total test files: {len(test_files)}")
    
    # Suggest missing tests
    print("\n💡 Suggested Test Files to Create:")
    
    priority_modules = [
        "src/agent/",
        "src/tools/",
        "src/features/",
        "api/routers/",
        "src/core/"
    ]
    
    for module_path in priority_modules:
        module_files = [f for f in all_files if str(f).startswith(module_path)]
        if module_files:
            print(f"\n  {module_path}")
            for file in module_files[:5]:  # Show first 5
                test_name = f"tests/test_{file.stem}.py"
                if not Path(test_name).exists():
                    print(f"    - {test_name}")


def print_coverage_tips():
    """Print tips for improving coverage"""
    print("\n" + "=" * 80)
    print("TIPS FOR IMPROVING COVERAGE")
    print("=" * 80)
    
    tips = [
        "1. Start with high-impact, frequently used modules",
        "2. Test edge cases and error conditions",
        "3. Use parametrized tests for similar test cases",
        "4. Mock external dependencies (APIs, databases)",
        "5. Test both success and failure paths",
        "6. Add integration tests for critical flows",
        "7. Use fixtures to reduce test code duplication",
        "8. Aim for at least 80% coverage on new code",
        "9. Review uncovered lines in HTML report",
        "10. Write tests before fixing bugs (TDD)"
    ]
    
    for tip in tips:
        print(f"  {tip}")
    
    print("\n📖 View detailed coverage report:")
    print("  open htmlcov/index.html")


def main():
    """Main function"""
    print("🧪 Test Coverage Analysis")
    print()
    
    # Run coverage
    success = run_coverage()
    
    if not success:
        print("\n❌ Tests failed. Fix failing tests before analyzing coverage.")
        return 1
    
    # Analyze coverage
    coverage = analyze_coverage()
    
    if coverage is None:
        print("\n❌ Could not analyze coverage")
        return 1
    
    # Generate badge
    generate_coverage_badge()
    
    # Identify missing tests
    identify_missing_tests()
    
    # Print tips
    print_coverage_tips()
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Current Coverage: {coverage:.2f}%")
    print(f"Target Coverage:  80.00%")
    print(f"Gap:              {max(0, 80 - coverage):.2f}%")
    
    if coverage >= 80:
        print("\n🎉 EXCELLENT! Coverage goal achieved!")
        return 0
    elif coverage >= 60:
        print("\n👍 Good coverage, keep improving!")
        return 0
    elif coverage >= 40:
        print("\n⚠️  Coverage needs improvement")
        return 0
    else:
        print("\n❌ Coverage is too low, focus on adding tests")
        return 1


if __name__ == "__main__":
    sys.exit(main())
