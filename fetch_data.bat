cd d:\python\trae_solo_space\trae_forum_scraper
python scrape_trae_forum.py --crawl-all --config config.example.json --min-delay 5 --max-delay 12
python build_app_data.py
python -m http.server 8000 -d app
