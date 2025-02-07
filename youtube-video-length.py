#!/usr/bin/env python3
"""
Search YouTube videos filtered by duration.

Usage examples:
  - Exact duration (ISO8601):
      python youtube-video-length.py -q "cat funny" -i PT14M7S
  - Exact duration (seconds):
      python youtube-video-length.py -q "cat funny" -s 411
  - Interval duration:
      python youtube-video-length.py -q "cat funny" --min-duration PT30M --max-duration PT40M
  - List without filtering by duration:
      python youtube-video-length.py -q "cat funny" -l

Note:
  The YouTube API key is loaded from the environment variable YOUTUBE_API_KEY.
"""

import argparse
import json
import re
import sys
import textwrap

import googleapiclient.discovery
import googleapiclient.errors
from environs import Env


def iso_time_duration_to_seconds(duration_iso: str) -> int:
    """
    Convert an ISO8601 duration string to total seconds.

    Parameters:
      duration_iso (str): ISO8601 duration string, e.g. "PT1H2M3S".

    Returns:
      int: Total seconds.

    Raises:
      ValueError: If the duration format is invalid or if any component is zero-padded.
    """
    pattern = (
        r'P'  # Duration starts with 'P'
        r'(?:(?P<days>\d{1,2})D)?'  # Optional days
        r'(?:T'  # 'T' starts the time part
        r'(?:(?P<hours>\d{1,2})H)?'  # Optional hours
        r'(?:(?P<minutes>\d{1,2})M)?'  # Optional minutes
        r'(?:(?P<seconds>\d{1,2})S)?'  # Optional seconds
        r')?$'
    )
    match = re.fullmatch(pattern, duration_iso)
    if not match:
        raise ValueError(f"Invalid ISO8601 duration format: {duration_iso}")

    # Enforce that no component is zero-padded (e.g. "PT05M" is disallowed)
    for part in ['days', 'hours', 'minutes', 'seconds']:
        value = match.group(part)
        if value and len(value) == 2 and value.startswith('0'):
            raise ValueError(f"Zero-padded value for {part}: {value}")

    parts = match.groupdict(default="0")
    days = int(parts['days'])
    hours = int(parts['hours'])
    minutes = int(parts['minutes'])
    seconds = int(parts['seconds'])
    total_seconds = days * 86400 + hours * 3600 + minutes * 60 + seconds
    return total_seconds


def get_video_duration(video_id: str, youtube: googleapiclient.discovery.Resource) -> str:
    """
    Retrieve the ISO8601 duration of a YouTube video.

    Parameters:
      video_id (str): The video ID.
      youtube (Resource): An instance of the YouTube API client.

    Returns:
      str: The video's duration (ISO8601).

    Raises:
      ValueError: If no video details are returned.
    """
    response = youtube.videos().list(
        part="contentDetails",
        id=video_id
    ).execute()
    items = response.get("items", [])
    if not items:
        raise ValueError(f"No video details found for video ID {video_id}")
    return items[0]["contentDetails"]["duration"]


def print_result(video_title: str, video_id: str, duration_iso: str, duration_seconds: int) -> None:
    """
    Print video details.
    """
    print(f"Video Title: {video_title}")
    print(f"Video ID: {video_id}")
    print(f"Video Duration (ISO): {duration_iso}")
    print(f"Video Duration (s): {duration_seconds} seconds\n")


def search_youtube_videos(api_key: str, query: str, max_results: int, mode: str,
                          target_seconds: int = None, min_seconds: int = None,
                          max_seconds: int = None, list_mode: bool = False) -> None:
    """
    Search YouTube videos by query and duration filter.

    Parameters:
      api_key (str): YouTube API key.
      query (str): The search query.
      max_results (int): Maximum number of results to retrieve.
      mode (str): 'exact', 'interval', or 'list'.
      target_seconds (int, optional): Target duration (exact match) in seconds.
      min_seconds (int, optional): Minimum duration in seconds (for interval mode).
      max_seconds (int, optional): Maximum duration in seconds (for interval mode).
      list_mode (bool): If True, no duration filtering is applied.
    """
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=api_key)

    # Determine YouTube API's duration category (short, medium, long) if possible.
    if list_mode:
        video_duration_category = 'any'
    elif mode == 'exact':
        if target_seconds < iso_time_duration_to_seconds("PT4M"):
            video_duration_category = 'short'
        elif target_seconds < iso_time_duration_to_seconds("PT20M"):
            video_duration_category = 'medium'
        else:
            video_duration_category = 'long'
    elif mode == 'interval':
        if max_seconds < iso_time_duration_to_seconds("PT4M"):
            video_duration_category = 'short'
        elif min_seconds >= iso_time_duration_to_seconds("PT4M") and max_seconds < iso_time_duration_to_seconds("PT20M"):
            video_duration_category = 'medium'
        elif min_seconds >= iso_time_duration_to_seconds("PT20M"):
            video_duration_category = 'long'
        else:
            video_duration_category = 'any'
    else:
        video_duration_category = 'any'

    try:
        search_response = youtube.search().list(
            q=query,
            part="id,snippet",
            type="video",
            videoDuration=video_duration_category,
            maxResults=max_results
        ).execute()
    except googleapiclient.errors.HttpError as e:
        try:
            error_info = json.loads(e.content.decode('utf-8'))
            error_message = error_info.get("error", {}).get("message", "Unknown error")
        except Exception:
            error_message = str(e)
        print(f"HTTP Error: {error_message}", file=sys.stderr)
        sys.exit(1)

    hit_count = 0
    for item in search_response.get("items", []):
        video_id = item["id"]["videoId"]
        video_title = item["snippet"]["title"]
        try:
            duration_iso = get_video_duration(video_id, youtube)
            duration_seconds = iso_time_duration_to_seconds(duration_iso)
        except Exception as ex:
            print(f"Error processing video {video_id}: {ex}", file=sys.stderr)
            continue

        if list_mode:
            print_result(video_title, video_id, duration_iso, duration_seconds)
            hit_count += 1
        elif mode == 'exact' and duration_seconds == target_seconds:
            print_result(video_title, video_id, duration_iso, duration_seconds)
            hit_count += 1
        elif mode == 'interval' and min_seconds <= duration_seconds <= max_seconds:
            print_result(video_title, video_id, duration_iso, duration_seconds)
            hit_count += 1

    if hit_count == 0:
        print("No matching videos found with the specified duration criteria.", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments.
    """
    parser = argparse.ArgumentParser(
        description=textwrap.dedent(
            """\
            Searches YouTube videos filtered by duration.

            Modes:
              * Exact match: Use -i (ISO8601) or -s (seconds) to find videos with exactly that duration.
              * Interval: Use --min-duration and/or --max-duration (ISO8601) to find videos within a range.
              * List: Use -l to list search results without filtering by duration.
            """
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # The API key is no longer passed as a command-line argument.
    parser.add_argument('-q', '--search-query', required=True, help='Search query, e.g. "cat funny"')
    parser.add_argument('-m', '--max-results', type=int, default=100, help='Maximum search results to retrieve')
    parser.add_argument('-t', '--test', action='store_true', help='Test the program with default arguments')

    # Mutually exclusive group for exact match or list mode.
    group = parser.add_mutually_exclusive_group()
    group.add_argument('-i', '--iso-8601', help='Exact duration in ISO8601 format, e.g. PT14M7S')
    group.add_argument('-s', '--seconds', type=int, help='Exact duration in seconds, e.g. 411')
    group.add_argument('-l', '--list', action='store_true', help='List results without filtering by duration')

    # Optional interval options.
    parser.add_argument('--min-duration', help='Minimum video duration (ISO8601), e.g. PT30M')
    parser.add_argument('--max-duration', help='Maximum video duration (ISO8601), e.g. PT40M')

    args = parser.parse_args()

    # Ensure that at least one duration filtering option is provided.
    if not (args.iso_8601 or args.seconds or args.list or args.min_duration or args.max_duration):
        parser.error(
            "You must provide one of the following: -i/--iso-8601, -s/--seconds, -l/--list, or --min-duration/--max-duration for an interval filter."
        )

    return args


def main() -> None:
    args = parse_args()

    # Load API key from environment variable using environs.
    env = Env()
    env.read_env()  # Automatically read from a .env file if present.
    api_key = env("YOUTUBE_API_KEY", None)
    if not api_key:
        print("Error: YOUTUBE_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    # Test mode: override arguments with test values.
    if args.test:
        query = "cat funny"
        mode = "interval"
        try:
            min_seconds = iso_time_duration_to_seconds("PT30M")
            max_seconds = iso_time_duration_to_seconds("PT40M")
        except ValueError as e:
            print(f"Test duration error: {e}", file=sys.stderr)
            sys.exit(1)
        target_seconds = None
    else:
        if args.list:
            mode = "list"
        elif args.iso_8601 or args.seconds:
            if args.min_duration or args.max_duration:
                print("Cannot mix exact duration options with interval options.", file=sys.stderr)
                sys.exit(1)
            mode = "exact"
        elif args.min_duration or args.max_duration:
            mode = "interval"
        else:
            print("No valid duration filter provided.", file=sys.stderr)
            sys.exit(1)

        if mode == "exact":
            try:
                target_seconds = args.seconds if args.seconds is not None else iso_time_duration_to_seconds(args.iso_8601)
            except ValueError as e:
                print(f"Duration parsing error: {e}", file=sys.stderr)
                sys.exit(1)
            min_seconds = max_seconds = None
        elif mode == "interval":
            try:
                min_seconds = iso_time_duration_to_seconds(args.min_duration) if args.min_duration else 0
                max_seconds = iso_time_duration_to_seconds(args.max_duration) if args.max_duration else float("inf")
            except ValueError as e:
                print(f"Duration parsing error: {e}", file=sys.stderr)
                sys.exit(1)
            target_seconds = None
        else:
            target_seconds = None
            min_seconds = max_seconds = None

        query = args.search_query

    search_youtube_videos(
        api_key=api_key,
        query=query,
        max_results=args.max_results,
        mode=mode,
        target_seconds=target_seconds,
        min_seconds=min_seconds,
        max_seconds=max_seconds,
        list_mode=(mode == "list")
    )


if __name__ == "__main__":
    main()
