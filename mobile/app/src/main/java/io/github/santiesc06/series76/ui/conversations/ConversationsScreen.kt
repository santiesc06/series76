package io.github.santiesc06.series76.ui.conversations

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ExitToApp
import androidx.compose.material.icons.filled.AccountCircle
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.santiesc06.series76.data.api.SessionSummary
import io.github.santiesc06.series76.data.auth.SignedInUser
import io.github.santiesc06.series76.ui.common.EmptyState
import io.github.santiesc06.series76.ui.common.ErrorState
import io.github.santiesc06.series76.ui.common.LoadingState
import io.github.santiesc06.series76.ui.common.formatRelativeTime

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConversationsScreen(
    user: SignedInUser,
    onLogout: () -> Unit,
    onOpen: (String) -> Unit,
    onNew: () -> Unit,
    viewModel: ConversationsViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    // Reload whenever the screen comes back (e.g. after a chat added a conversation).
    LifecycleResumeEffect(Unit) {
        viewModel.refresh()
        onPauseOrDispose { }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Series 76 Assistant") },
                actions = { AccountMenu(user, onLogout) },
            )
        },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = onNew,
                icon = { Icon(Icons.Filled.Add, contentDescription = null) },
                text = { Text("New conversation") },
            )
        },
    ) { padding ->
        val modifier = Modifier.padding(padding).fillMaxSize()
        when (val s = state) {
            ConversationsUiState.Loading -> LoadingState(modifier, "Loading conversations…")
            is ConversationsUiState.Error ->
                ErrorState(s.error.message, onRetry = viewModel::refresh, modifier = modifier)
            is ConversationsUiState.Loaded -> PullToRefreshBox(
                isRefreshing = s.refreshing,
                onRefresh = viewModel::refresh,
                modifier = modifier,
            ) {
                if (s.sessions.isEmpty()) {
                    EmptyState(
                        title = "No conversations yet",
                        body = "Ask about a part number or describe your requirements to get a " +
                            "recommendation.",
                    )
                } else {
                    SessionList(s.sessions, onOpen)
                }
            }
        }
    }
}

@Composable
private fun SessionList(sessions: List<SessionSummary>, onOpen: (String) -> Unit) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(bottom = 96.dp), // keep the last item above the button
    ) {
        items(sessions, key = { it.id }) { session ->
            ListItem(
                headlineContent = {
                    Text(session.title, maxLines = 2, overflow = TextOverflow.Ellipsis)
                },
                supportingContent = {
                    val questions = session.messageCount / 2
                    Text(
                        "${formatRelativeTime(session.updatedAt)} · " +
                            "$questions ${if (questions == 1) "question" else "questions"}",
                    )
                },
                modifier = Modifier.clickable { onOpen(session.id) },
            )
            HorizontalDivider()
        }
    }
}

/** Who is signed in, and logout (US-21 AC8). */
@Composable
private fun AccountMenu(user: SignedInUser, onLogout: () -> Unit) {
    var open by remember { mutableStateOf(false) }
    IconButton(onClick = { open = true }) {
        Icon(Icons.Filled.AccountCircle, contentDescription = "Account")
    }
    DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
        DropdownMenuItem(
            text = {
                Column {
                    Text(user.name.ifBlank { "Signed in" })
                    Text(user.email, style = MaterialTheme.typography.bodySmall)
                }
            },
            leadingIcon = { Icon(Icons.Filled.AccountCircle, contentDescription = null) },
            onClick = {},
            enabled = false,
        )
        HorizontalDivider()
        DropdownMenuItem(
            text = { Text("Log out") },
            leadingIcon = {
                Icon(Icons.AutoMirrored.Filled.ExitToApp, contentDescription = null)
            },
            onClick = {
                open = false
                onLogout()
            },
        )
    }
}
