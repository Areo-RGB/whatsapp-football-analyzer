"""
WhatsApp CLI (wacli) wrapper.
Provides Python interface for wacli commands.
"""

import json
import subprocess
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


def get_sender_phones(message_ids: list[str], store_dir: str | None = None) -> dict[str, str]:
    """
    Look up actual sender phone numbers for messages from whatsmeow session.db.
    
    wacli stores group JID as sender_jid for group messages, but the real sender
    info is in whatsmeow_message_secrets table, which can be joined with 
    whatsmeow_lid_map to get the actual phone number.
    
    Args:
        message_ids: List of message IDs to look up
        store_dir: Optional wacli store directory (default: ~/.wacli)
        
    Returns:
        Dict mapping message_id -> phone number (e.g., "4917632223598")
    """
    if not message_ids:
        return {}
    
    store_path = Path(store_dir) if store_dir else Path.home() / ".wacli"
    session_db = store_path / "session.db"
    
    if not session_db.exists():
        return {}
    
    try:
        conn = sqlite3.connect(str(session_db))
        cursor = conn.cursor()
        
        # Build query with placeholders for message IDs
        placeholders = ",".join("?" * len(message_ids))
        query = f"""
            SELECT 
                ms.message_id,
                lm.pn as phone
            FROM whatsmeow_message_secrets ms
            LEFT JOIN whatsmeow_lid_map lm 
                ON substr(ms.sender_jid, 1, instr(ms.sender_jid, '@')-1) = lm.lid
            WHERE ms.message_id IN ({placeholders})
        """
        
        cursor.execute(query, message_ids)
        results = {row[0]: row[1] for row in cursor.fetchall() if row[1]}
        
        conn.close()
        return results
        
    except Exception as e:
        # Silently fail - phone lookup is optional enhancement
        return {}




def check_wacli() -> bool:
    """Check if wacli is installed and available."""
    return shutil.which('wacli') is not None


def run_wacli(*args, json_output: bool = False, timeout: int = 60) -> tuple[int, str, str]:
    """
    Run a wacli command.
    
    Args:
        *args: Command arguments
        json_output: Whether to add --json flag
        timeout: Command timeout in seconds
        
    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    cmd = ['wacli']
    if json_output:
        cmd.append('--json')
    cmd.extend(args)
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except FileNotFoundError:
        return -1, "", "wacli not found. Install from: https://github.com/steipete/wacli"


@dataclass
class Chat:
    """Represents a WhatsApp chat."""
    jid: str
    name: str
    is_group: bool
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Chat':
        return cls(
            jid=data.get('JID', data.get('jid', '')),
            name=data.get('Name', data.get('name', '')),
            is_group='@g.us' in data.get('JID', data.get('jid', ''))
        )


@dataclass
class WacliMessage:
    """Represents a message from wacli."""
    id: str
    chat_jid: str
    sender: str
    text: str
    timestamp: str
    has_media: bool
    media_type: str | None
    
    @classmethod
    def from_dict(cls, data: dict) -> 'WacliMessage':
        # Handle wacli's field naming (MsgID, ChatJID, SenderJID, etc.)
        media_type = data.get('MediaType', data.get('media_type', ''))
        return cls(
            id=data.get('MsgID', data.get('ID', data.get('id', ''))),
            chat_jid=data.get('ChatJID', data.get('chat_jid', '')),
            sender=data.get('SenderJID', data.get('Sender', data.get('sender', ''))),
            text=data.get('Text', data.get('text', '')),
            timestamp=data.get('Timestamp', data.get('timestamp', '')),
            has_media=bool(media_type),
            media_type=media_type if media_type else None
        )


class WacliClient:
    """Python client for wacli commands."""
    
    def __init__(self, store_dir: str | None = None):
        """
        Initialize wacli client.
        
        Args:
            store_dir: Optional custom store directory (default: ~/.wacli)
        """
        self.store_dir = store_dir
        self._check_installation()
    
    def _check_installation(self):
        """Verify wacli is installed."""
        if not check_wacli():
            raise RuntimeError(
                "wacli is not installed. Install from: https://github.com/steipete/wacli"
            )
    
    def _run(self, *args, json_output: bool = True, timeout: int = 60) -> tuple[int, str, str]:
        """Run wacli with optional store directory."""
        cmd_args = list(args)
        if self.store_dir:
            cmd_args = ['--store', self.store_dir] + cmd_args
        return run_wacli(*cmd_args, json_output=json_output, timeout=timeout)
    
    def is_authenticated(self) -> bool:
        """Check if wacli is authenticated."""
        code, _, _ = self._run('doctor', json_output=False, timeout=10)
        return code == 0
    
    def list_chats(self, limit: int = 100) -> list[Chat]:
        """
        List available chats.
        
        Args:
            limit: Maximum number of chats to return
            
        Returns:
            List of Chat objects
        """
        code, stdout, stderr = self._run('chats', 'list', '--limit', str(limit))
        
        if code != 0:
            raise RuntimeError(f"Failed to list chats: {stderr}")
        
        try:
            response = json.loads(stdout)
            # Handle nested response structure
            data = response.get('data', response) if isinstance(response, dict) else response
            if isinstance(data, list):
                return [Chat.from_dict(c) for c in data]
            return []
        except json.JSONDecodeError:
            return []
    
    def list_groups(self) -> list[Chat]:
        """List available groups."""
        code, stdout, stderr = self._run('groups', 'list')
        
        if code != 0:
            raise RuntimeError(f"Failed to list groups: {stderr}")
        
        try:
            response = json.loads(stdout)
            # Handle nested response structure
            data = response.get('data', response) if isinstance(response, dict) else response
            if isinstance(data, list):
                return [Chat.from_dict(g) for g in data]
            return []
        except json.JSONDecodeError:
            return []
    
    def search_messages(self, query: str, limit: int = 100) -> list[WacliMessage]:
        """
        Search messages.
        
        Args:
            query: Search query
            limit: Maximum number of results
            
        Returns:
            List of matching messages
        """
        code, stdout, stderr = self._run(
            'messages', 'search', query,
            '--limit', str(limit)
        )
        
        if code != 0:
            raise RuntimeError(f"Failed to search messages: {stderr}")
        
        try:
            data = json.loads(stdout)
            return [WacliMessage.from_dict(m) for m in data]
        except json.JSONDecodeError:
            return []
    
    def get_messages(self, chat_jid: str, limit: int = 100) -> list[WacliMessage]:
        """
        Get messages from a specific chat.
        
        Args:
            chat_jid: Chat JID (e.g., "1234567890@s.whatsapp.net")
            limit: Maximum number of messages
            
        Returns:
            List of messages
        """
        code, stdout, stderr = self._run(
            'messages', 'list',
            '--chat', chat_jid,
            '--limit', str(limit)
        )
        
        if code != 0:
            raise RuntimeError(f"Failed to get messages: {stderr}")
        
        try:
            response = json.loads(stdout)
            # Handle nested response: {success, data: {messages: [...]}}
            if isinstance(response, dict):
                data = response.get('data', response)
                if isinstance(data, dict):
                    messages = data.get('messages', [])
                elif isinstance(data, list):
                    messages = data
                else:
                    messages = []
            else:
                messages = response if isinstance(response, list) else []
            return [WacliMessage.from_dict(m) for m in messages]
        except json.JSONDecodeError:
            return []
    
    def send_message(self, to: str, message: str) -> bool:
        """
        Send a text message.
        
        Args:
            to: Recipient phone number or JID
            message: Message text
            
        Returns:
            True if sent successfully
        """
        # Normalize phone number
        if not '@' in to:
            # Remove non-digits except leading +
            clean = ''.join(c for c in to if c.isdigit() or c == '+')
            if clean.startswith('+'):
                clean = clean[1:]
            to = f"{clean}@s.whatsapp.net"
        
        code, stdout, stderr = self._run(
            'send', 'text',
            '--to', to,
            '--message', message,
            json_output=False,
            timeout=30
        )
        
        return code == 0
    
    def send_to_group(self, group_jid: str, message: str) -> bool:
        """
        Send a message to a group.
        
        Args:
            group_jid: Group JID (e.g., "123456789@g.us")
            message: Message text
            
        Returns:
            True if sent successfully
        """
        code, stdout, stderr = self._run(
            'send', 'text',
            '--to', group_jid,
            '--message', message,
            json_output=False,
            timeout=30
        )
        
        return code == 0
    
    def send_image(self, group_jid: str, image_path: str, caption: str = None) -> bool:
        """
        Send an image to a group.
        
        Args:
            group_jid: Group JID (e.g., "123456789@g.us")
            image_path: Path to image file
            caption: Optional caption for the image
            
        Returns:
            True if sent successfully
        """
        args = [
            'send', 'file',
            '--to', group_jid,
            '--file', str(image_path),
        ]
        
        if caption:
            args.extend(['--caption', caption])
        
        code, stdout, stderr = self._run(
            *args,
            json_output=False,
            timeout=60
        )
        
        return code == 0
    
    def download_media(self, chat_jid: str, message_id: str, output_dir: str | Path) -> str | None:
        """
        Download media from a message.
        
        Args:
            chat_jid: Chat JID
            message_id: Message ID
            output_dir: Directory to save media
            
        Returns:
            Path to downloaded file, or None if failed
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        code, stdout, stderr = self._run(
            'media', 'download',
            '--chat', chat_jid,
            '--id', message_id,
            '--output', str(output_dir),
            json_output=False,
            timeout=120
        )
        
        if code == 0:
            # Try to find downloaded file
            # wacli typically saves with message ID in filename
            for f in output_dir.iterdir():
                if message_id in f.name:
                    return str(f)
        
        return None
    
    def sync(self, follow: bool = False, timeout: int = 300) -> bool:
        """
        Sync messages from WhatsApp.
        
        Args:
            follow: Keep syncing continuously
            timeout: Timeout for initial sync
            
        Returns:
            True if sync started/completed successfully
        """
        args = ['sync']
        if follow:
            args.append('--follow')
        
        code, stdout, stderr = self._run(
            *args,
            json_output=False,
            timeout=timeout if not follow else 5
        )
        
        # For --follow mode, we expect timeout (process keeps running)
        return code == 0 or (follow and code == -1)


def find_group_by_name(client: WacliClient, name_part: str) -> Chat | None:
    """Find a group by partial name match."""
    name_lower = name_part.lower()
    
    # Search in groups first
    groups = client.list_groups()
    for group in groups:
        if name_lower in group.name.lower():
            return group
    
    # Also search in chats (some groups appear there)
    chats = client.list_chats(limit=200)
    for chat in chats:
        if chat.is_group and name_lower in chat.name.lower():
            return chat
    
    return None


if __name__ == "__main__":
    print("WhatsApp CLI Wrapper Test")
    print(f"wacli available: {check_wacli()}")
    
    if check_wacli():
        try:
            client = WacliClient()
            print(f"Authenticated: {client.is_authenticated()}")
            
            print("\nListing groups...")
            groups = client.list_groups()
            for g in groups[:5]:
                print(f"  - {g.name} ({g.jid})")
        except Exception as e:
            print(f"Error: {e}")
