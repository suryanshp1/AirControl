from .gesture import Gesture
from pynput.keyboard import Key, Controller
import subprocess

keyboard = Controller()

def execute_mac_action(gesture: Gesture):
    """Executes macOS system media commands depending on the gesture."""
    
    try:
        if gesture == Gesture.OPEN_PALM:
            keyboard.press(Key.media_play_pause)
            keyboard.release(Key.media_play_pause)
        elif gesture == Gesture.FIST:
            keyboard.press(Key.media_play_pause)
            keyboard.release(Key.media_play_pause)
        elif gesture == Gesture.SWIPE_RIGHT:
            keyboard.press(Key.media_next)
            keyboard.release(Key.media_next)
        elif gesture == Gesture.SWIPE_LEFT:
            keyboard.press(Key.media_previous)
            keyboard.release(Key.media_previous)
        elif gesture == Gesture.PINCH_UP:
            # Volume can sometimes be finicky with pynput on macOS, 
            # so we keep AppleScript as a fallback/primary for volume.
            subprocess.run(['osascript', '-e', 'set volume output volume (output volume of (get volume settings) + 10)'], check=True)
        elif gesture == Gesture.PINCH_DOWN:
            subprocess.run(['osascript', '-e', 'set volume output volume (output volume of (get volume settings) - 10)'], check=True)
            
        print(f"Executed action for gesture: {gesture.name}")
    except Exception as e:
        print(f"Failed to execute action: {e}")
