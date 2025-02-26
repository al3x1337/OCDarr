import os
import requests
import logging
import json
from dotenv import load_dotenv

# Load settings from a JSON configuration file
def load_config():
    config_path = os.getenv('CONFIG_PATH', '/app/config/config.json')
    with open(config_path, 'r') as file:
        config = json.load(file)
    return config

config = load_config()

# Load environment variables
load_dotenv()

# Define global variables based on environment settings
SONARR_URL = os.getenv('SONARR_URL')
SONARR_API_KEY = os.getenv('SONARR_API_KEY')
LOG_PATH = os.getenv('LOG_PATH', '/app/logs/app.log')
MISSING_LOG_PATH = os.getenv('MISSING_LOG_PATH', '/app/logs/missing.log')

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()
handler = logging.FileHandler(LOG_PATH)
logger.addHandler(handler)
missing_logger = logging.getLogger('missing')
missing_handler = logging.FileHandler(MISSING_LOG_PATH)
missing_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
missing_logger.addHandler(missing_handler)

def get_server_activity():
    """Read current viewing details from Tautulli webhook stored data."""
    try:
        with open('/app/temp/data_from_tautulli.json', 'r') as file:
            data = json.load(file)
        series_title = data['plex_title']
        season_number = int(data['plex_season_num'])
        episode_number = int(data['plex_ep_num'])
        return series_title, season_number, episode_number
    except Exception as e:
        logger.error(f"Failed to read or parse data from Tautulli webhook: {str(e)}")
    return None, None, None

def get_series_id(series_name):
    """Fetch series ID by name from Sonarr."""
    url = f"{SONARR_URL}/api/v3/series"
    headers = {'X-Api-Key': SONARR_API_KEY}
    response = requests.get(url, headers=headers)
    if response.ok:
        series_list = response.json()
        for series in series_list:
            if series['title'].lower() == series_name.lower():
                return series['id']
        missing_logger.info(f"Series not found in Sonarr: {series_name}")
    else:
        logger.error("Failed to fetch series from Sonarr.")
    return None

def get_episode_details(series_id, season_number):
    """Fetch details of episodes for a specific series and season from Sonarr."""
    url = f"{SONARR_URL}/api/v3/episode?seriesId={series_id}&seasonNumber={season_number}"
    headers = {'X-Api-Key': SONARR_API_KEY}
    response = requests.get(url, headers=headers)
    if response.ok:
        episode_details = response.json()
        return episode_details
    logger.error("Failed to fetch episode details.")
    return []

def get_series_title(series_id):
    """Fetch series title by series ID from Sonarr."""
    url = f"{SONARR_URL}/api/v3/series/{series_id}"
    headers = {'X-Api-Key': SONARR_API_KEY}
    response = requests.get(url, headers=headers)
    if response.ok:
        return response.json()['title']
    logger.error("Failed to fetch series title.")
    return None

def monitor_episodes(episode_ids, monitor=True):
    """Set episodes to monitored or unmonitored in Sonarr."""
    url = f"{SONARR_URL}/api/v3/episode/monitor"
    headers = {'X-Api-Key': SONARR_API_KEY, 'Content-Type': 'application/json'}
    data = {"episodeIds": episode_ids, "monitored": monitor}
    response = requests.put(url, json=data, headers=headers)
    if response.ok:
        logger.info(f"Episodes {episode_ids} set to monitored: {monitor}")
    else:
        logger.error(f"Failed to set episodes to monitored. Response: {response.text}")

def trigger_episode_search_in_sonarr(episode_ids):
    """Trigger a search for specified episodes in Sonarr."""
    url = f"{SONARR_URL}/api/v3/command"
    headers = {'X-Api-Key': SONARR_API_KEY, 'Content-Type': 'application/json'}
    data = {"name": "EpisodeSearch", "episodeIds": episode_ids}
    response = requests.post(url, json=data, headers=headers)
    if response.ok:
        logger.info("Episode search command sent to Sonarr successfully.")
    else:
        logger.error(f"Failed to send episode search command. Response: {response.text}")

def unmonitor_episodes(episode_ids):
    """Unmonitor specified episodes in Sonarr."""
    unmonitor_url = f"{SONARR_URL}/api/v3/episode/monitor"
    unmonitor_data = {"episodeIds": episode_ids, "monitored": False}
    unmonitor_headers = {'X-Api-Key': SONARR_API_KEY, 'Content-Type': 'application/json'}
    response = requests.put(unmonitor_url, json=unmonitor_data, headers=unmonitor_headers)
    if response.ok:
        logger.info(f"Episodes {episode_ids} unmonitored successfully.")
    else:
        logger.error(f"Failed to unmonitor episodes. Response: {response.text}")

def find_episodes_to_delete(all_episodes, keep_watched, last_watched_id):
    """Find episodes to delete, ensuring they're not in the keep list and have files."""
    episodes_to_delete = []
    if keep_watched == "all":
        return episodes_to_delete
    elif keep_watched == "season":
        last_watched_season = max(ep['seasonNumber'] for ep in all_episodes if ep['id'] == last_watched_id)
        episodes_to_delete = [ep['episodeFileId'] for ep in all_episodes if ep['seasonNumber'] < last_watched_season and ep['episodeFileId'] > 0]
    elif isinstance(keep_watched, int):
        episodes_to_delete = [ep['episodeFileId'] for ep in all_episodes if ep['id'] < last_watched_id and ep['episodeFileId'] > 0]
        episodes_to_delete = episodes_to_delete[:len(episodes_to_delete) - keep_watched]

    return episodes_to_delete

def delete_episodes_in_sonarr(episode_file_ids):
    """Delete specified episodes in Sonarr."""
    if not episode_file_ids:
        logger.info("No episodes to delete.")
        return

    failed_deletes = []
    for episode_file_id in episode_file_ids:
        try:
            url = f"{SONARR_URL}/api/v3/episodeFile/{episode_file_id}"
            headers = {'X-Api-Key': SONARR_API_KEY}
            response = requests.delete(url, headers=headers)
            response.raise_for_status()  # Raise an HTTPError for bad responses
            logger.info(f"Successfully deleted episode file with ID: {episode_file_id}")
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP error occurred: {http_err} - Response: {response.text}")
            failed_deletes.append(episode_file_id)
        except Exception as err:
            logger.error(f"Other error occurred: {err}")
            failed_deletes.append(episode_file_id)
    
    if failed_deletes:
        logger.error(f"Failed to delete the following episode files: {failed_deletes}")

def fetch_next_episodes(series_id, season_number, episode_number, num_episodes):
    """Fetch the next num_episodes episodes starting from the given season and episode."""
    next_episode_ids = []

    # Get remaining episodes in the current season
    current_season_episodes = get_episode_details(series_id, season_number)
    next_episode_ids.extend([ep['id'] for ep in current_season_episodes if ep['episodeNumber'] > episode_number])

    # Fetch episodes from the next season if needed
    next_season_number = season_number + 1
    while len(next_episode_ids) < int(num_episodes):
        next_season_episodes = get_episode_details(series_id, next_season_number)
        next_episode_ids.extend([ep['id'] for ep in next_season_episodes])
        next_season_number += 1

    return next_episode_ids[:int(num_episodes)]

def fetch_all_episodes(series_id):
    """Fetch all episodes for a series from Sonarr."""
    all_episodes = []
    url = f"{SONARR_URL}/api/v3/episode?seriesId={series_id}"
    headers = {'X-Api-Key': SONARR_API_KEY}
    response = requests.get(url, headers=headers)
    if response.ok:
        all_episodes = response.json()
    return all_episodes

def delete_old_episodes(series_id, keep_episode_ids):
    """Delete old episodes that are not in the keep list."""
    all_episodes = fetch_all_episodes(series_id)
    episodes_with_files = [ep for ep in all_episodes if ep['hasFile']]
    episodes_to_delete = [ep['episodeFileId'] for ep in episodes_with_files if ep['id'] not in keep_episode_ids]
    delete_episodes_in_sonarr(episodes_to_delete)

def main():
    series_name, season_number, episode_number = get_server_activity()
    if series_name:
        series_id = get_series_id(series_name)
        if series_id:
            all_episodes = fetch_all_episodes(series_id)
            if all_episodes:
                next_episode_ids = fetch_next_episodes(series_id, season_number, episode_number, config['get_option'])
                if next_episode_ids:
                    monitor_episodes(next_episode_ids, monitor=True)
                    if config['action_option'] == "search":
                        trigger_episode_search_in_sonarr(next_episode_ids)

                    last_watched_id = next(ep['id'] for ep in all_episodes if ep['seasonNumber'] == season_number and ep['episodeNumber'] == episode_number)
                    episodes_to_delete = find_episodes_to_delete(all_episodes, config['keep_watched'], last_watched_id)
                    delete_episodes_in_sonarr(episodes_to_delete)

                    keep_episode_ids = next_episode_ids + [last_watched_id]
                    delete_old_episodes(series_id, keep_episode_ids)
                else:
                    logger.info("No next episodes found to monitor.")
            else:
                logger.info("No episodes found for the current series.")
        else:
            logger.info(f"Series ID not found for series: {series_name}")
    else:
        logger.info("No server activity found.")

if __name__ == "__main__":
    main()
