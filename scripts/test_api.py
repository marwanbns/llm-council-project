"""
LLM Council - API Test Script
Tests the API endpoints to verify the system is working.
"""

import asyncio
import httpx
import sys

API_BASE = "http://localhost:8000"


async def test_health():
    """Test the health endpoint."""
    print("Testing /api/health...")
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{API_BASE}/api/health", timeout=10)
            data = response.json()
            
            print(f"  Status: {data.get('status')}")
            print(f"  Nodes: {len(data.get('nodes', []))}")
            
            for node in data.get('nodes', []):
                status_icon = "✅" if node['status'] == 'online' else "❌"
                latency = f"{node.get('latency_ms', 0):.0f}ms" if node.get('latency_ms') else "N/A"
                chairman = " 👑" if node.get('is_chairman') else ""
                print(f"    {status_icon} {node['name']} ({node['model']}) - {latency}{chairman}")
            
            return data.get('status') == 'healthy'
        except Exception as e:
            print(f"  ❌ Error: {e}")
            return False


async def test_status():
    """Test the status endpoint."""
    print("\nTesting /api/status...")
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{API_BASE}/api/status", timeout=10)
            data = response.json()
            
            print(f"  System Status: {data.get('system_status')}")
            print(f"  Active Sessions: {data.get('active_sessions')}")
            print(f"  Total Sessions: {data.get('total_sessions')}")
            print(f"  Council Members: {len(data.get('council_members', []))}")
            
            return True
        except Exception as e:
            print(f"  ❌ Error: {e}")
            return False


async def test_query():
    """Test a simple query."""
    print("\nTesting /api/council/query...")
    print("  (This may take a minute...)")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{API_BASE}/api/council/query",
                json={"query": "What is 2 + 2? Answer briefly."},
                timeout=120
            )
            data = response.json()
            
            print(f"  Session ID: {data.get('session_id')}")
            print(f"  Stage: {data.get('stage')}")
            print(f"  Opinions: {len(data.get('first_opinions', []))}")
            
            if data.get('chairman_synthesis'):
                print(f"  Chairman Response: {data['chairman_synthesis'].get('final_response', '')[:100]}...")
            
            return data.get('stage') == 'completed'
        except Exception as e:
            print(f"  ❌ Error: {e}")
            return False


async def main():
    print("=" * 50)
    print("LLM Council API Test Suite")
    print("=" * 50)
    print()
    
    results = []
    
    # Test health
    results.append(("Health Check", await test_health()))
    
    # Test status
    results.append(("Status Check", await test_status()))
    
    # Ask user if they want to run the full query test
    print("\n" + "-" * 50)
    run_query = input("Run full query test? (y/n): ").lower().strip()
    
    if run_query == 'y':
        results.append(("Query Test", await test_query()))
    
    # Summary
    print("\n" + "=" * 50)
    print("Test Summary")
    print("=" * 50)
    
    all_passed = True
    for name, passed in results:
        icon = "✅" if passed else "❌"
        print(f"  {icon} {name}")
        if not passed:
            all_passed = False
    
    print()
    if all_passed:
        print("🎉 All tests passed!")
        return 0
    else:
        print("⚠️  Some tests failed. Check the logs above.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
