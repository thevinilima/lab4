import csv
import re
from statistics import mean, median
from datetime import datetime
from math import ceil
import requests

GITHUB_API_URL = "https://api.github.com/graphql"
GITHUB_TOKEN = ""

# GraphQL query to get popular repositories with issue counts
def create_query(after_cursor=None):
    return f"""
    {{
      search(query: "stars:>10000", type: REPOSITORY, first: 10 {f'after: "{after_cursor}"' if after_cursor else ''}) {{
        edges {{
          node {{
            ... on Repository {{
              name
              owner {{
                login
              }}
              stargazerCount
              issues {{
                totalCount
              }}
            }}
          }}
          cursor
        }}
        pageInfo {{
          hasNextPage
          endCursor
        }}
      }}
    }}
    """


# Function to make a GraphQL request
def run_query(query):
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    response = requests.post(GITHUB_API_URL, json={"query": query}, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Query failed with code {response.status_code}: {response.text}")


# Function to get repositories with more than 100 issues
def get_repos_with_issues(limit):
    repos = []
    has_next_page = True
    after_cursor = None

    while has_next_page and len(repos) < limit:
        query = create_query(after_cursor)
        result = run_query(query)

        # Process the repositories from the current page
        for edge in result['data']['search']['edges']:
            repo = edge['node']
            if repo['issues']['totalCount'] > 100:
                repos.append({
                    'name': repo['name'],
                    'owner': repo['owner']['login'],
                    'stargazers': repo['stargazerCount'],
                    'issues': repo['issues']['totalCount']
                })
                if len(repos) >= limit:
                    break

        # Check if there are more pages
        page_info = result['data']['search']['pageInfo']
        has_next_page = page_info['hasNextPage']
        after_cursor = page_info['endCursor']

    return repos


def calculate_time_difference(start_time, end_time):
    start = datetime.strptime(start_time, "%Y-%m-%dT%H:%M:%SZ")
    end = datetime.strptime(end_time, "%Y-%m-%dT%H:%M:%SZ")
    return (end - start).total_seconds()


# Update GraphQL query to retrieve issue body, labels, etc.
def create_issues_query(repo_owner, repo_name, after_cursor=None):
    return f"""
    {{
      repository(owner: "{repo_owner}", name: "{repo_name}") {{
        issues(first: 100, {f'after: "{after_cursor}"' if after_cursor else ''}, orderBy: {{field: CREATED_AT, direction: DESC}}) {{
          edges {{
            node {{
              title
              createdAt
              body
              labels(first: 5) {{
                nodes {{
                  name
                }}
              }}
              comments(first: 1, orderBy: {{field: UPDATED_AT, direction: ASC}}) {{
                edges {{
                  node {{
                    createdAt
                  }}
                }}
              }}
            }}
            cursor
          }}
          pageInfo {{
            hasNextPage
            endCursor
          }}
        }}
      }}
    }}
    """


def get_issues_with_response_times(repo_owner, repo_name):
    issues_with_response_time = []
    has_next_page = True
    after_cursor = None

    while has_next_page:
        query = create_issues_query(repo_owner, repo_name, after_cursor)
        result = run_query(query)

        # Process the issues from the current page
        for edge in result['data']['repository']['issues']['edges']:
            issue = edge['node']
            created_at = issue['createdAt']
            comments = issue['comments']['edges']

            # If there is at least one comment, calculate the response time
            if comments:
                first_comment_time = comments[0]['node']['createdAt']
                response_time = calculate_time_difference(created_at, first_comment_time)
            else:
                # If there are no comments, set response_time as None
                response_time = None

            # Collect attributes (checklist, reference links, labels, images, code)
            body = issue['body']
            attributes = {
                'has_checklist': bool(re.search(r'- \[[ x]\]', body)),
                'has_reference_links': bool(re.search(r'http[s]?://', body)),
                'has_images': bool(re.search(r'!\[.*?\]\(.*?\)', body)),
                'has_code': bool(re.search(r'```', body)),
                'labels': [label['name'] for label in issue['labels']['nodes']]
            }

            issues_with_response_time.append({
                'title': issue['title'],
                'created_at': created_at,
                'response_time': response_time,
                'attributes': attributes
            })

        # Check if there are more pages
        page_info = result['data']['repository']['issues']['pageInfo']
        has_next_page = page_info['hasNextPage']
        after_cursor = page_info['endCursor']

    return issues_with_response_time


# Function to separate the 10% fastest and 10% slowest response times
def separate_fastest_and_slowest_issues(issues, percentage=10):
    issues_with_response = [issue for issue in issues if issue['response_time'] is not None]
    issues_with_response.sort(key=lambda x: x['response_time'])  # Sort by response time

    count = ceil(len(issues_with_response) * percentage / 100)  # 10% of total issues

    # 10% with fastest response times
    fastest_issues = issues_with_response[:count]

    # 10% with longest response times
    slowest_issues = issues_with_response[-count:]

    return fastest_issues, slowest_issues


# Function to collect statistics for attributes
def collect_statistics(issues):
    total_issues = len(issues)  # Total number of issues

    checklist_count = sum(issue['attributes']['has_checklist'] for issue in issues)
    reference_count = sum(issue['attributes']['has_reference_links'] for issue in issues)
    image_count = sum(issue['attributes']['has_images'] for issue in issues)
    code_count = sum(issue['attributes']['has_code'] for issue in issues)
    label_count = sum(bool(issue['attributes']['labels']) for issue in issues)  # Count issues with labels

    response_times = [issue['response_time'] for issue in issues if issue['response_time'] is not None]

    stats = {
        'checklist_percentage': (checklist_count / total_issues * 100) if total_issues > 0 else 0,
        'reference_percentage': (reference_count / total_issues * 100) if total_issues > 0 else 0,
        'image_percentage': (image_count / total_issues * 100) if total_issues > 0 else 0,
        'code_percentage': (code_count / total_issues * 100) if total_issues > 0 else 0,
        'mean_response_time': mean(response_times) if response_times else None,
        'label_percentage': (label_count / total_issues * 100) if total_issues > 0 else 0,
        'median_response_time': median(response_times) if response_times else None,
    }

    return stats


# Function to save statistics to a CSV file
def save_stats_to_csv(stats, file_name):
    keys = stats[0].keys()  # Get the keys (column names) from the first entry
    with open(file_name, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=keys)
        writer.writeheader()  # Write the header
        writer.writerows(stats)  # Write the rows of data


# Main function to run the script
if __name__ == "__main__":
    # Set the limit to get the first X repositories with more than 100 issues
    X = 10
    repos = get_repos_with_issues(X)

    # Lists to collect all fastest and slowest stats for all repos
    all_fastest_stats = []
    all_slowest_stats = []

    # Process each repository
    for repo in repos:
        print(f"Repository: {repo['owner']}/{repo['name']} - Stars: {repo['stargazers']}, Issues: {repo['issues']}")
        issues = get_issues_with_response_times(repo['owner'], repo['name'])
        fastest_issues, slowest_issues = separate_fastest_and_slowest_issues(issues)

        # Get statistics for fastest and slowest issues
        fastest_stats = collect_statistics(fastest_issues)
        slowest_stats = collect_statistics(slowest_issues)

        # Add stats to the lists
        all_fastest_stats.append(fastest_stats)
        all_slowest_stats.append(slowest_stats)

        print(f"\nFastest 10% issues for {repo['owner']}/{repo['name']} - Stats: {fastest_stats}")
        print(f"Slowest 10% issues for {repo['owner']}/{repo['name']} - Stats: {slowest_stats}")

    # Save all the fastest and slowest stats to CSV files
    save_stats_to_csv(all_fastest_stats, 'fastest_stats.csv')
    save_stats_to_csv(all_slowest_stats, 'slowest_stats.csv')
