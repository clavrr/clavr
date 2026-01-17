import asyncio
import unittest
from unittest.mock import MagicMock, patch
from src.integrations.linear.client import LinearClient, LinearAPIException

class TestLinearClientSDK(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.api_key = "test_key"
        self.client = LinearClient(api_key=self.api_key)

    @patch("src.integrations.linear.client.LinearSDK")
    async def test_get_viewer(self, mock_sdk_class):
        # Setup mock
        mock_sdk = mock_sdk_class.return_value
        mock_viewer = MagicMock()
        mock_viewer.model_dump.return_value = {"id": "user_1", "name": "Test User"}
        
        # Configure both possible methods
        mock_sdk.users.get_viewer.return_value = mock_viewer
        mock_sdk.users.get_me.return_value = mock_viewer
        
        # Execute
        viewer = await self.client.get_viewer()
        
        # Verify
        self.assertEqual(viewer["id"], "user_1")
        self.assertEqual(viewer["name"], "Test User")

    @patch("src.integrations.linear.client.LinearSDK")
    async def test_get_teams(self, mock_sdk_class):
        # Setup mock
        mock_sdk = mock_sdk_class.return_value
        mock_team = MagicMock()
        mock_team.model_dump.return_value = {"id": "team_1", "name": "Engineering"}
        mock_sdk.teams.get_all.return_value = {"team_1": mock_team}
        
        # Execute
        teams = await self.client.get_teams()
        
        # Verify
        self.assertEqual(len(teams), 1)
        self.assertEqual(teams[0]["name"], "Engineering")

    @patch("src.integrations.linear.client.LinearSDK")
    async def test_get_cycles(self, mock_sdk_class):
        # Setup mock
        mock_sdk = mock_sdk_class.return_value
        mock_sdk.execute_graphql.return_value = {
            "cycles": {
                "nodes": [
                    {"id": "cycle_1", "name": "Cycle 1"}
                ]
            }
        }
        
        # Execute
        cycles = await self.client.get_cycles(team_id="team_1")
        
        # Verify
        self.assertEqual(len(cycles), 1)
        self.assertEqual(cycles[0]["name"], "Cycle 1")
        mock_sdk.execute_graphql.assert_called_once()

    @patch("src.integrations.linear.client.LinearSDK")
    async def test_create_issue(self, mock_sdk_class):
        # Setup mock
        mock_sdk = mock_sdk_class.return_value
        
        mock_team = MagicMock()
        mock_team.name = "Engineering"
        mock_sdk.teams.get.return_value = mock_team
        
        mock_issue = MagicMock()
        mock_issue.model_dump.return_value = {"id": "issue_1", "title": "New Issue"}
        mock_sdk.issues.create.return_value = mock_issue
        
        # Execute
        issue = await self.client.create_issue(
            title="New Issue",
            team_id="team_1",
            description="Test description"
        )
        
        # Verify
        self.assertEqual(issue["id"], "issue_1")
        self.assertEqual(issue["title"], "New Issue")
        mock_sdk.issues.create.assert_called_once()

    @patch("src.integrations.linear.client.LinearSDK")
    async def test_get_projects(self, mock_sdk_class):
        # Setup mock
        mock_sdk = mock_sdk_class.return_value
        mock_project = MagicMock()
        mock_project.model_dump.return_value = {"id": "proj_1", "name": "DeepMind Integration"}
        mock_sdk.projects.get_all.return_value = {"proj_1": mock_project}
        
        # Execute
        projects = await self.client.get_projects()
        
        # Verify
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["name"], "DeepMind Integration")

    @patch("src.integrations.linear.client.LinearSDK")
    async def test_add_comment(self, mock_sdk_class):
        # Setup mock
        mock_sdk = mock_sdk_class.return_value
        mock_sdk.execute_graphql.return_value = {
            "commentCreate": {
                "comment": {"id": "comm_1", "body": "Test comment"}
            }
        }
        
        # Execute
        comment = await self.client.add_comment("issue_1", "Test comment")
        
        # Verify
        self.assertEqual(comment["id"], "comm_1")
        self.assertEqual(comment["body"], "Test comment")

    @patch("src.integrations.linear.client.LinearSDK")
    async def test_get_issue_comments(self, mock_sdk_class):
        # Setup mock
        mock_sdk = mock_sdk_class.return_value
        mock_comment = MagicMock()
        mock_comment.model_dump.return_value = {"id": "comm_1", "body": "Test comment"}
        mock_sdk.issues.get_comments.return_value = [mock_comment]
        
        # Execute
        comments = await self.client.get_issue_comments("issue_1")
        
        # Verify
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["body"], "Test comment")
