package io.github.santiesc06.series76.navigation

import androidx.compose.runtime.Composable
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import io.github.santiesc06.series76.devtools.DevTools
import io.github.santiesc06.series76.ui.chat.ChatScreen
import io.github.santiesc06.series76.ui.conversations.ConversationsScreen
import kotlinx.serialization.Serializable

@Serializable
object ConversationsRoute

/** `sessionId == null` opens an empty chat; the backend creates the session on the first message. */
@Serializable
data class ChatRoute(val sessionId: String? = null)

@Composable
fun AppNavHost() {
    val navController = rememberNavController()
    NavHost(navController = navController, startDestination = ConversationsRoute) {
        composable<ConversationsRoute> {
            ConversationsScreen(
                onOpen = { id -> navController.navigate(ChatRoute(sessionId = id)) },
                onNew = { navController.navigate(ChatRoute()) },
            )
        }
        composable<ChatRoute> {
            ChatScreen(
                onBack = { navController.popBackStack() },
                // Only the debug build has the developer screen (design M5, US-19 AC2).
                onOpenDebug = if (DevTools.ENABLED) {
                    { messageId -> DevTools.openMessageDetails(navController, messageId) }
                } else {
                    null
                },
            )
        }
        DevTools.registerDestinations(this, navController)
    }
}
