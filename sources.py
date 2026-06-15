"""Source registry for the Unofficial Guide RAG pipeline.

This mirrors the Documents table in planning.md. The `type` field decides how
each source is fetched and cleaned during ingestion (see ingest.py):

    "reddit"  -> fetched via Reddit's public .json endpoint (title + post + comments)
    "website" -> fetched as HTML and stripped of nav/script/boilerplate
    "pdf"     -> downloaded and parsed with pdfplumber

To add or swap a source, edit this list and keep planning.md in sync.
"""

SOURCES = [
    {"id": 1,  "type": "reddit",  "url": "https://www.reddit.com/r/QueensCollege/comments/1g45ejk/parking/"},
    {"id": 2,  "type": "reddit",  "url": "https://www.reddit.com/r/QueensCollege/comments/yptzg/where_to_park_at_queens_college/"},
    {"id": 3,  "type": "website", "url": "https://www.qc.cuny.edu/ps/parking-traffic-regulations/"},
    {"id": 4,  "type": "website", "url": "https://www.qc.cuny.edu/ps/parking/"},
    {"id": 5,  "type": "reddit",  "url": "https://www.reddit.com/r/nycrail/comments/1mf0m7n/driving_to_nyc_from_fl_staying_in_queens_for_7/"},
    {"id": 6,  "type": "pdf",     "url": "https://www.qc.cuny.edu/ps/wp-content/uploads/sites/56/2025/06/Parking-Instructions-2025-2026.pdf"},
    {"id": 7,  "type": "website", "url": "https://www.qc.cuny.edu/a/campus-access/"},
    {"id": 8,  "type": "reddit",  "url": "https://www.reddit.com/r/AskNYC/comments/wl183a/do_we_trust_spothero/"},
    {"id": 9,  "type": "website", "url": "https://www.spotangels.com/blog/nyc-parking-tickets-where-youre-likely-to-get-one-and-how-spotangels-can-pay-for-it/"},
    {"id": 10, "type": "reddit",  "url": "https://www.reddit.com/r/QueensCollege/comments/12toied/anyone_have_some_parking_tips/"},
]
