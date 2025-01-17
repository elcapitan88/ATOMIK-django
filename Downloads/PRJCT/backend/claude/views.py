from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import anthropic
import json
import logging

logger = logging.getLogger(__name__)

@csrf_exempt
def chat_with_claude(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            user_message = data.get('message', '')
            logger.info(f"Received message: {user_message}")

            client = anthropic.Anthropic(api_key=settings.CLAUDE_API_KEY)
            logger.info("Anthropic client created successfully")

            message = client.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=1024,
                messages=[
                    {"role": "user", "content": user_message}
                ]
            )
            logger.info("Message created successfully")
            
            return JsonResponse({'response': message.content[0].text})
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {str(e)}")
            return JsonResponse({'error': 'Invalid JSON in request body'}, status=400)
        except Exception as e:
            logger.error(f"Error in chat_with_claude: {str(e)}", exc_info=True)
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'error': 'Invalid request method'}, status=400)