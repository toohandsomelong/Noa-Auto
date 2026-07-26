import pyautogui
from pynput import keyboard, mouse

# def on_click(x, y, button, pressed):
#     if pressed:
#         print(f"Mouse clicked at: ({x}, {y})")

# with mouse.Listener(on_click=on_click) as listener:
#     listener.join()

def on_press(key):
    try:
        if key.char == 'x':
            print("Global press detected: 'x'")
            pyautogui.scroll(-100, x=550, y=542)
    except AttributeError:
        pass

def on_release(key):
    try:
        if key.char == 'x':
            print("Global release detected: 'x'")
    except AttributeError:
        pass
        
    if key == keyboard.Key.esc:
        print("Stopping listener...")
        return False

# Start the global keyboard listener session
with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
    listener.join()